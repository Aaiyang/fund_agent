import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Async, EmptyState, LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Screen, SectionTitle, Stat } from '@/components/ui';
import { NavChart } from '@/components/NavChart';
import { theme } from '@/constants/theme';
import { NAV_RANGES, useFundDetail, useFundNav, useRefreshFund, type NavRange } from '@/hooks/useFunds';
import { usePosition } from '@/hooks/usePortfolio';
import { useAddWatchlistFund, useRemoveWatchlistFund, useWatchlist } from '@/hooks/useWatchlist';
import { useUiStore } from '@/stores/ui';
import {
  formatDate,
  formatDateTime,
  formatMoney,
  formatNumber,
  formatRate,
  formatReturnPoints,
  formatSignedMoney,
  trendColor,
} from '@/utils/format';

/** Fund detail: overview + holdings context + NAV chart (spec 3.5). */
export default function FundDetailScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const [range, setRange] = useState<NavRange>('1y');
  const accountId = useUiStore((state) => state.accountId);
  const groupId = useUiStore((state) => state.groupId);
  const detail = useFundDetail(code ?? null);
  const nav = useFundNav(code ?? null, range);
  const position = usePosition(accountId, code ?? null);
  const watchlist = useWatchlist(null);
  const add = useAddWatchlistFund();
  const remove = useRemoveWatchlistFund();
  const refresh = useRefreshFund(code ?? null);
  const [notice, setNotice] = useState<string | null>(null);

  const isWatchlisted = (watchlist.data?.items ?? []).some((item) => item.fund_code === code);

  function toggleWatchlist() {
    if (!code) return;
    setNotice(null);
    if (isWatchlisted) {
      remove.mutate(code, { onError: (error) => setNotice(error.message) });
      return;
    }
    add.mutate(
      { fund_code: code, group_ids: groupId ? [groupId] : [] },
      { onError: (error) => setNotice(error.message) },
    );
  }

  return (
    <Screen>
      {detail.isPending ? <LoadingState /> : null}
      {detail.isError ? (
        <Card>
          <Text style={{ color: theme.danger, fontSize: 14 }}>{describeError(detail.error)}</Text>
        </Card>
      ) : null}

      {detail.data ? (
        <Card>
          <Text style={{ fontSize: 18, fontWeight: '700', color: theme.text }}>{detail.data.fund_name}</Text>
          <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
            {detail.data.fund_code}
            {detail.data.fund_type ? ` · ${detail.data.fund_type}` : ''}
            {detail.data.company ? ` · ${detail.data.company}` : ''}
          </Text>
          <View style={{ flexDirection: 'row', alignItems: 'flex-end', marginVertical: 12 }}>
            <Text style={{ fontSize: 30, fontWeight: '700', color: theme.text, marginRight: 10 }}>
              {formatNumber(detail.data.latest_nav)}
            </Text>
            <Text style={{ fontSize: 16, color: trendColor(detail.data.daily_return ?? 0) }}>
              {formatReturnPoints(detail.data.daily_return)}
            </Text>
          </View>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
            <Stat label="净值日期" value={formatDate(detail.data.nav_date)} tone="muted" />
            <Stat label="累计净值" value={formatNumber(detail.data.accumulated_nav)} />
            <Stat label="成立日期" value={formatDate(detail.data.inception_date)} tone="muted" />
            <Stat label="基金经理" value={detail.data.manager_name ?? '--'} tone="muted" />
          </View>
          <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 4 }}>
            来源 {detail.data.source ?? '--'} · 数据截止 {formatDate(detail.data.source_as_of)} · 抓取于{' '}
            {formatDateTime(detail.data.nav_fetched_at ?? detail.data.updated_at)}
          </Text>
        </Card>
      ) : null}

      {detail.data ? (
        <Card>
          <SectionTitle title="业绩走势" action="同步净值" onAction={() => refresh.mutate()} />
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 8 }}>
            {NAV_RANGES.map((item) => (
              <Chip key={item.key} label={item.label} active={range === item.key} onPress={() => setRange(item.key)} />
            ))}
          </View>
          <Async query={nav}>{(data) => <NavChart points={data.points} />}</Async>
          {detail.data.performance ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 10 }}>
              <Stat label="近 1 月" value={formatRate(detail.data.performance.return_1m)} tone={trendTone(detail.data.performance.return_1m)} />
              <Stat label="近 3 月" value={formatRate(detail.data.performance.return_3m)} tone={trendTone(detail.data.performance.return_3m)} />
              <Stat label="近 6 月" value={formatRate(detail.data.performance.return_6m)} tone={trendTone(detail.data.performance.return_6m)} />
              <Stat label="近 1 年" value={formatRate(detail.data.performance.return_1y)} tone={trendTone(detail.data.performance.return_1y)} />
              <Stat label="近 3 年" value={formatRate(detail.data.performance.return_3y)} tone={trendTone(detail.data.performance.return_3y)} />
              <Stat label="成立以来" value={formatRate(detail.data.performance.return_since_inception)} tone={trendTone(detail.data.performance.return_since_inception)} />
              <Stat label="最大回撤" value={formatRate(detail.data.performance.max_drawdown)} tone="down" />
              <Stat label="年化波动率" value={formatRate(detail.data.performance.annualized_volatility)} tone="muted" />
            </View>
          ) : null}
          {notice ? <Text style={{ fontSize: 12, color: theme.warning }}>{notice}</Text> : null}
          {refresh.isPending ? <Text style={{ fontSize: 12, color: theme.textMuted }}>已提交同步任务，稍后自动刷新…</Text> : null}
        </Card>
      ) : null}

      <Card>
        <SectionTitle title="我的持仓" action="修改持仓" onAction={() => router.push(`/position/edit?code=${code}&account_id=${accountId ?? ''}`)} />
        <Async
          query={position}
          empty={() => <EmptyState title="该账户未持有此基金" hint="可点击“修改持仓”手动录入" />}
        >
          {(data) => (
            <View>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                <Stat label="持有金额" value={formatMoney(data.market_value)} />
                <Stat label="持有份额" value={formatNumber(data.shares)} />
                <Stat label="持仓占比" value={formatRate(data.position_ratio)} />
                <Stat label="持有收益" value={formatSignedMoney(data.profit_loss)} tone={trendTone(data.profit_loss)} />
                <Stat label="持有收益率" value={formatRate(data.profit_loss_rate)} tone={trendTone(data.profit_loss_rate)} />
                <Stat label="持仓成本净值" value={formatNumber(data.average_cost_nav)} />
                <Stat label="当日收益" value={formatSignedMoney(data.daily_profit_loss)} tone={trendTone(data.daily_profit_loss)} />
                <Stat label="持有天数" value={data.holding_days !== null && data.holding_days !== undefined ? `${data.holding_days}` : '--'} tone="muted" />
              </View>
              <Text style={{ fontSize: 11, color: theme.textFaint }}>
                成本 {formatMoney(data.cost_amount)} · 更新于 {formatDateTime(data.updated_at)} · 版本 v{data.version}
              </Text>
            </View>
          )}
        </Async>
      </Card>

      <View style={{ flexDirection: 'row', marginTop: 4 }}>
        <View style={{ flex: 1, marginRight: 6 }}>
          <Button label="交易记录" variant="secondary" onPress={() => router.push(`/transactions?fund_code=${code}`)} />
        </View>
        <View style={{ flex: 1, marginLeft: 6 }}>
          <Button label={isWatchlisted ? '删除自选' : '加自选'} onPress={toggleWatchlist} loading={add.isPending || remove.isPending} />
        </View>
      </View>
      <View style={{ marginTop: 10 }}>
        <Button label="问 Agent" variant="secondary" onPress={() => router.push(`/(tabs)/agent?fund_code=${code}`)} />
      </View>
    </Screen>
  );
}

function trendTone(value: number | null | undefined): 'up' | 'down' | 'normal' {
  if (value === null || value === undefined || value === 0) return 'normal';
  return value > 0 ? 'up' : 'down';
}
