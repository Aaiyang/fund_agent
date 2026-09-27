import { router } from 'expo-router';
import { useRef } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Chip, Screen, SectionTitle } from '@/components/ui';
import { HoldingsTable } from '@/components/HoldingsTable';
import { theme } from '@/constants/theme';
import { useIndexQuotes } from '@/hooks/useIndexes';
import { useDragScroll } from '@/hooks/useDragScroll';
import { useAccounts, usePortfolioSummary, usePositions } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import {
  formatDateTime,
  formatMoney,
  formatNumber,
  formatRate,
  formatReturnPoints,
  formatSignedMoney,
  trendColor,
} from '@/utils/format';

export default function HoldingsScreen() {
  const accountId = useUiStore((state) => state.accountId);
  const setAccountId = useUiStore((state) => state.setAccountId);
  const summary = usePortfolioSummary(accountId);
  const positions = usePositions(accountId);
  const accounts = useAccounts();
  const quotes = useIndexQuotes();
  const tapeRef = useRef<ScrollView>(null);
  useDragScroll(tapeRef);
  const tape = (quotes.data?.items ?? []).map((index) => ({
    key: index.index_code,
    label: index.name,
    value: formatNumber(index.close, 2),
    change: formatReturnPoints(index.change_pct),
    tone: trendColor(index.change_pct),
  }));

  return (
    <Screen
      pinned={
        <View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
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
          </ScrollView>
          <Text style={{ fontSize: 11, color: theme.textFaint }}>
            共 {accounts.data?.total ?? 0} 个账户 · 切换账户只影响下方统计与列表
          </Text>
          <ScrollView
            ref={tapeRef}
            horizontal
            showsHorizontalScrollIndicator={false}
            style={{ marginTop: 2 }}
          >
            {tape.map((entry) => (
              <View key={entry.key} style={{ flexDirection: 'row', alignItems: 'baseline', marginRight: 16 }}>
                <Text style={{ fontSize: 12, color: theme.textMuted }}>{entry.label}</Text>
                {entry.value ? (
                  <Text style={{ fontSize: 13, color: theme.text, marginLeft: 5 }}>{entry.value}</Text>
                ) : null}
                <Text style={{ fontSize: 12, color: entry.tone, marginLeft: 5 }}>{entry.change}</Text>
              </View>
            ))}
          </ScrollView>
        </View>
      }
    >
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
                <Metric label="昨日收益" value={formatSignedMoney(stats.daily_profit_loss)} color={trendColor(stats.daily_profit_loss)} />
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
          {(data) => <HoldingsTable items={data.items} />}
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
