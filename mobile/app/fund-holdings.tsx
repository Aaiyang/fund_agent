/**
 * Top-ten disclosed holdings of one fund, in the same grid as 自选/持仓.
 *
 * The disclosure is quarterly and the quotes are live, so the row shows the
 * quote timestamp: during a session it is today's time, otherwise the last
 * closed session's — which is what "开盘看实时、休市看最新" looks like in data.
 */

import { Stack, useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import { useFundDetail, useFundHoldings, type FundHoldingItem } from '@/hooks/useFunds';
import { formatDate, formatNumber, formatPoints, formatReturnPoints, trendColor } from '@/utils/format';
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
      sub: item.quote_time ? item.quote_time.slice(5, 16).replace('/', '-') : '--',
    }),
  },
  {
    key: 'delta',
    title: '较上期占比',
    width: 96,
    sortValue: (item) => item.weight_change,
    cell: (item) =>
      item.is_new
        ? { text: '新增', color: theme.primary }
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
            // The schema defaults `items` to an empty list, so it arrives optional.
            const items = data.items ?? [];
            return (
              <View>
                <Text style={{ fontSize: 12, color: theme.textMuted }}>
                  披露期 {data.quarter ?? '--'}
                  {data.previous_quarter ? ` · 对比 ${data.previous_quarter}` : ''}
                </Text>
                <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }}>
                  持仓为季度披露，涨幅为个股行情，页面停留期间每 30 秒刷新一次
                </Text>
                {items.length === 0 ? (
                  <EmptyState title="暂无重仓股披露" hint="该基金尚未公布定期报告的股票持仓" />
                ) : (
                  <DataTable
                    items={items}
                    padded={false}
                    scrollRows={false}
                    style={{ marginTop: 10 }}
                    keyOf={(item) => item.stock_code}
                    nameOf={(item) => ({ title: item.stock_name ?? item.stock_code, sub: item.stock_code })}
                    columns={COLUMNS}
                    hint="点表头排序（再点切换升/降） · 左右滑动查看其它列"
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
              <Text style={{ fontSize: 11, color: theme.textFaint, marginBottom: 10 }}>
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
    <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
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
