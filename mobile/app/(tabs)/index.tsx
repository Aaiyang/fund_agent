import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Chip, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useAccounts, usePortfolioSummary, usePositions } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import { formatDateTime, formatMoney, formatRate, formatSignedMoney, trendColor } from '@/utils/format';

export default function HoldingsScreen() {
  const accountId = useUiStore((state) => state.accountId);
  const setAccountId = useUiStore((state) => state.setAccountId);
  const summary = usePortfolioSummary(accountId);
  const positions = usePositions(accountId);
  const accounts = useAccounts();

  return (
    <Screen>
      <Card>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 4 }}>
          <Chip label="账户汇总" active={accountId === null} onPress={() => setAccountId(null)} />
          {(accounts.data?.items ?? []).map((account) => (
            <Chip
              key={account.id}
              label={account.name}
              active={accountId === account.id}
              onPress={() => setAccountId(account.id)}
            />
          ))}
          <Chip label="+ 添加账户" onPress={() => router.push('/account/add')} />
        </View>
        <Text style={{ fontSize: 12, color: theme.textFaint }}>
          共 {accounts.data?.total ?? 0} 个账户 · 切换账户只影响下方统计与列表
        </Text>
      </Card>

      <Async query={summary}>
        {(data) => {
          const stats = data.summary;
          return (
            <Card>
              <Text style={{ fontSize: 13, color: theme.textMuted }}>总资产（元）</Text>
              <Text style={{ fontSize: 30, fontWeight: '700', color: theme.text, marginVertical: 4 }}>
                {formatMoney(stats.total_market_value)}
              </Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                <Metric label="当日收益" value={formatSignedMoney(stats.daily_profit_loss)} color={trendColor(stats.daily_profit_loss)} />
                <Metric label="累计收益" value={formatSignedMoney(stats.total_profit_loss)} color={trendColor(stats.total_profit_loss)} />
                <Metric label="累计收益率" value={formatRate(stats.total_profit_loss_rate)} color={trendColor(stats.total_profit_loss)} />
                <Metric label="持仓数量" value={`${stats.fund_count}`} color={theme.text} />
              </View>
              <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 6 }}>
                数据更新：{formatDateTime(stats.data_updated_at)}
              </Text>
            </Card>
          );
        }}
      </Async>

      <Card>
        <SectionTitle title="持仓基金" action="导入持仓" onAction={() => router.push('/holding-import')} />
        <Async
          query={positions}
          empty={(data) =>
            data.items.length === 0 ? (
              <EmptyState
                title="还没有持仓"
                hint="手动录入或上传第三方 App 持仓截图导入；截图结果需要你确认后才写入。"
              />
            ) : null
          }
        >
          {(data) => (
            <View>
              {data.items.map((position) => (
                <FundRow
                  key={`${position.account_id}-${position.fund_code}`}
                  fundCode={position.fund_code}
                  fundName={position.fund_name ?? position.fund_code}
                  latestNav={position.market_value}
                  dailyReturn={position.daily_return}
                  navDate={position.nav_date}
                  extra={`占比 ${formatRate(position.position_ratio)} · 持有 ${formatMoney(position.profit_loss)}`}
                  badges={position.is_updated ? [] : [{ label: '净值未更新', tone: 'muted' }]}
                />
              ))}
              <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 10 }}>
                左列显示的是持有金额；收益率与占比由后端在查询时计算，不落库。
              </Text>
            </View>
          )}
        </Async>
      </Card>
    </Screen>
  );
}

function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <View style={{ width: '50%', marginBottom: 10 }}>
      <Text style={{ fontSize: 12, color: theme.textFaint }}>{label}</Text>
      <Text style={{ fontSize: 17, fontWeight: '600', color }}>{value}</Text>
    </View>
  );
}
