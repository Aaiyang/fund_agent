/**
 * 展示某基金披露报告中的前十大重仓股，沿用自选/持仓同款表格布局。
 *
 * 持仓披露按季度出、行情是实时的，所以每行带上行情时间戳：盘中是今天的时间，
 * 休市时是最近一个收盘场次的时间——“开盘看实时、休市看最新”落到数据上就是这样。
 */

import { Stack, useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import { useFundDetail, useFundHoldings, type FundHoldingItem } from '@/hooks/useFunds';
import { formatDate, formatDay, formatNumber, formatPoints, formatReturnPoints, localToday, trendColor } from '@/utils/format';

/**
 * 行情时间戳的上游形状随市场而变（A股 `2026-10-08 14:30:00`、港股带斜杠、美股是另一套），
 * 这一列只是让人扫读，所以认得出日期与时分才显示：今天/昨天用相对说法，更早给月日，跨年补年份。
 * 认不出来就留 `--`，不把原始串糊进表格。
 */
function formatQuoteTime(value: string | null | undefined): string {
  if (!value) return '--';
  const matched = /^(\d{4})[-/](\d{2})[-/](\d{2})[ T](\d{2}:\d{2})/.exec(value.trim());
  if (!matched) return '--';
  const [, year, month, day, clock] = matched;
  const dayValue = `${year}-${month}-${day}`;
  const now = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (dayValue === localToday()) return `今天 ${clock}`;
  if (dayValue === formatDay(yesterday)) return `昨天 ${clock}`;
  return year === String(now.getFullYear()) ? `${month}-${day} ${clock}` : dayValue;
}

const COLUMNS: DataColumn<FundHoldingItem>[] = [
  { key: 'weight', title: '持仓占比', width: 84, sortValue: (item) => item.weight, cell: (item) => ({ text: formatPoints(item.weight) }) },
  {
    key: 'change',
    title: '实时涨幅',
    width: 92,
    sortValue: (item) => item.change_pct,
    cell: (item) => ({
      text: formatReturnPoints(item.change_pct),
      color: trendColor(item.change_pct),
      sub: formatQuoteTime(item.quote_time),
    }),
  },
  {
    key: 'delta',
    title: '较上期占比',
    width: 96,
    sortValue: (item) => item.weight_change,
    cell: (item) =>
      item.is_new
        ? { text: '新增', color: theme.text, align: 'center' }
        : { text: formatReturnPoints(item.weight_change), color: trendColor(item.weight_change) },
  },
  { key: 'price', title: '现价', width: 84, sortValue: (item) => item.price, cell: (item) => ({ text: formatNumber(item.price, 2) }) },
];

export default function FundHoldingsScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const detail = useFundDetail(code ?? null);
  const holdings = useFundHoldings(code ?? null);

  return (
    <Screen>
      <Stack.Screen options={{ title: '前十大重仓股' }} />
      <Card>
        <SectionTitle title={detail.data?.fund_name ?? `基金 ${code ?? ''}`} />
        <Async query={holdings}>
          {(data) => {
            // schema 里 `items` 的默认值是空列表，所以响应中该字段可能缺席。
            const items = data.items ?? [];
            return (
              <View>
                <Text style={{ fontSize: 12, color: theme.textMuted }}>
                  披露期 {data.quarter ?? '--'}
                  {data.previous_quarter ? ` · 对比 ${data.previous_quarter}` : ''}
                </Text>
                {items.length === 0 ? (
                  <EmptyState title="还没有重仓股披露" hint="这只基金还没公布定期报告，返回详情可看净值走势" />
                ) : (
                  <DataTable
                    items={items}
                    padded={false}
                    scrollRows={false}
                    style={{ marginTop: 8 }}
                    keyOf={(item) => item.stock_code}
                    hrefOf={(item) => ({ pathname: '/market/[symbol]', params: { symbol: item.symbol ?? item.stock_code } })}
                    nameOf={(item) => ({ title: item.stock_name ?? item.stock_code, sub: item.stock_code })}
                    columns={COLUMNS}
                  />
                )}
              </View>
            );
          }}
        </Async>
      </Card>

      <Async query={holdings}>
        {(data) => {
          const industries = data.industries ?? [];
          if (industries.length === 0) return null;
          return (
            <Card>
              <SectionTitle title="行业分布" />
              <Text style={{ fontSize: 11, color: theme.textFaint, marginBottom: 8 }}>
                占净值比例 · 披露截止 {formatDate(data.industries_as_of)}
              </Text>
              {industries.map((industry) => (
                <IndustryBar
                  key={industry.industry}
                  name={industry.industry ?? '--'}
                  weight={industry.weight}
                  share={Math.max(...industries.map((row) => row.weight ?? 0))}
                />
              ))}
            </Card>
          );
        }}
      </Async>
    </Screen>
  );
}

function IndustryBar({ name, weight, share }: { name: string; weight: number | null | undefined; share: number }) {
  const value = weight ?? 0;
  const width = share > 0 ? Math.max((value / share) * 100, 1.5) : 0;
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
      <Text style={{ width: 104, fontSize: 12, color: theme.textMuted, marginRight: 8 }} numberOfLines={1}>
        {name}
      </Text>
      <View style={{ flex: 1, height: 10, backgroundColor: theme.background, borderRadius: 5, overflow: 'hidden' }}>
        <View style={{ width: `${width}%`, height: 10, backgroundColor: theme.primary, borderRadius: 5 }} />
      </View>
      <Text style={{ width: 56, fontSize: 12, color: theme.text, textAlign: 'right' }}>{formatPoints(weight)}</Text>
    </View>
  );
}
