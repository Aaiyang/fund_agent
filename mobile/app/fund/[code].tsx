import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';
import { SymbolView } from 'expo-symbols';

import { Async, EmptyState, LoadingState, describeError } from '@/components/states';
import { GroupPicker } from '@/components/GroupPicker';
import { Button, Card, Chip, Screen, SectionTitle, Stat } from '@/components/ui';
import { NavChart } from '@/components/NavChart';
import { theme } from '@/constants/theme';
import { NAV_RANGES, useFundDetail, useFundNav, useRefreshFund, type NavRange } from '@/hooks/useFunds';
import { DEFAULT_BENCHMARK, useIndexCatalog, useIndexHistory } from '@/hooks/useIndexes';
import { usePosition } from '@/hooks/usePortfolio';
import {
  useAddWatchlistFund,
  useCreateWatchlistGroup,
  useRemoveWatchlistFund,
  useWatchlist,
  useWatchlistGroups,
} from '@/hooks/useWatchlist';
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

const NAV_ROWS_COLLAPSED = 15;

/** 提示条：成功用主色、失败用警示色，同一屏只留一处渲染点。 */
type Notice = { text: string; error: boolean };

/** 基金详情页：概览 + 我的持仓上下文 + 净值走势图（spec 3.5）。 */
export default function FundDetailScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const [range, setRange] = useState<NavRange>('1y');
  const [benchmarkCode, setBenchmarkCode] = useState<string | null>(DEFAULT_BENCHMARK);
  const [pickingBenchmark, setPickingBenchmark] = useState(false);
  const accountId = useUiStore((state) => state.accountId);
  const detail = useFundDetail(code ?? null);
  const nav = useFundNav(code ?? null, range);
  const benchmark = useIndexHistory(benchmarkCode, range);
  const catalog = useIndexCatalog();
  const position = usePosition(accountId, code ?? null);
  const watchlist = useWatchlist(null);
  const groups = useWatchlistGroups();
  const add = useAddWatchlistFund();
  const createGroup = useCreateWatchlistGroup();
  const remove = useRemoveWatchlistFund();
  const refresh = useRefreshFund(code ?? null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pickingGroup, setPickingGroup] = useState(false);

  const isWatchlisted = (watchlist.data?.items ?? []).some((item) => item.fund_code === code);

  function toggleWatchlist() {
    if (!code) return;
    setNotice(null);
    if (isWatchlisted) {
      remove.mutate(code, { onError: (error) => setNotice({ text: describeError(error), error: true }) });
      return;
    }
    // 加自选从不静默进行：先让用户挑选分组，或明确选择“不分组”（spec 3.3）。
    setPickingGroup(true);
  }

  async function createGroupNamed(name: string): Promise<number | null> {
    try {
      const group = await createGroup.mutateAsync({ name });
      return group.id;
    } catch (error) {
      setNotice({ text: describeError(error), error: true });
      return null;
    }
  }

  const navPoints = nav.data?.points ?? [];
  const recentNav = [...navPoints].reverse().slice(0, NAV_ROWS_COLLAPSED);
  const benchmarkOptions = (catalog.data?.items ?? []).map((item) => ({ value: item.index_code, label: item.name }));

  return (
    <Screen refreshing={refresh.isPending} onRefresh={code ? () => refresh.mutate() : undefined}>
      <Stack.Screen options={{ headerRight: () => <StarButton active={isWatchlisted} onPress={toggleWatchlist} /> }} />

      {detail.isPending ? <LoadingState /> : null}
      {detail.isError ? (
        <Card>
          <Text style={{ color: theme.danger, fontSize: 14 }}>{describeError(detail.error)}</Text>
        </Card>
      ) : null}

      {detail.data ? (
        <Card>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="查看前十大重仓股"
            onPress={() => router.push(`/fund-holdings?code=${code}`)}
            style={({ pressed }) => [{ opacity: pressed ? 0.85 : 1 }]}
          >
            <Text style={{ fontSize: 18, fontWeight: '700', color: theme.text }}>{detail.data.fund_name}</Text>
            <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
              {detail.data.fund_code}
              {detail.data.fund_type ? ` · ${detail.data.fund_type}` : ''}
              {detail.data.company ? ` · ${detail.data.company}` : ''}
            </Text>

            <View style={{ flexDirection: 'row', alignItems: 'baseline', marginTop: 8 }}>
              <Text style={{ fontSize: 21, fontWeight: '700', color: trendColor(detail.data.daily_return) }}>
                {formatReturnPoints(detail.data.daily_return)}
              </Text>
              <Text style={{ fontSize: 12, color: theme.textFaint, marginLeft: 8 }}>
                {formatDate(detail.data.nav_date)}
              </Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
              <Text style={{ fontSize: 12, color: theme.textMuted }}>单位净值</Text>
              <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginLeft: 6 }}>
                {formatNumber(detail.data.latest_nav)}
              </Text>
              <Text style={{ fontSize: 12, color: theme.textMuted, marginLeft: 14 }}>累计净值</Text>
              <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginLeft: 6 }}>
                {formatNumber(detail.data.accumulated_nav)}
              </Text>
            </View>

            <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
              <Stat label="成立日期" value={formatDate(detail.data.inception_date)} tone="muted" />
              <Stat label="基金经理" value={detail.data.manager_name ?? '--'} tone="muted" />
              <Stat label="规模" value={detail.data.asset_size ?? '--'} tone="muted" />
            </View>
            <Text style={{ fontSize: 12, color: theme.primary, marginTop: 2 }}>前十大重仓股 ›</Text>
          </Pressable>
        </Card>
      ) : null}

      {detail.data ? (
        <Card>
          <SectionTitle title="业绩走势" />
          <Async query={nav}>
            {(data) =>
              data.points.length === 0 ? (
                <EmptyState title="还没有净值数据" hint="下拉刷新可触发同步" />
              ) : (
                <NavChart
                  points={data.points}
                  benchmark={
                    benchmarkCode && benchmark.data
                      ? { name: benchmark.data.name, points: benchmark.data.points }
                      : null
                  }
                  costNav={position.data?.average_cost_nav ?? null}
                  benchmarkPicker={{
                    open: pickingBenchmark,
                    options: benchmarkOptions,
                    selected: benchmarkCode,
                    onToggle: () => setPickingBenchmark((open) => !open),
                    onPick: (indexCode) => {
                      setBenchmarkCode(indexCode);
                      setPickingBenchmark(false);
                    },
                  }}
                />
              )
            }
          </Async>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            {NAV_RANGES.map((item) => (
              <Chip key={item.key} label={item.label} active={range === item.key} onPress={() => setRange(item.key)} />
            ))}
          </ScrollView>
          {detail.data.performance ? (
            <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
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
          {refresh.isPending ? <Text style={{ fontSize: 11, color: theme.textMuted }}>已提交同步任务，稍后自动刷新…</Text> : null}
        </Card>
      ) : null}

      <Card>
        <SectionTitle title="净值明细" />
        <Async query={nav}>
          {(data) =>
            data.points.length === 0 ? (
              <EmptyState title="还没有净值记录" hint="下拉刷新可触发同步" />
            ) : (
              <View>
                <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.border, paddingBottom: 6 }}>
                  <Text style={{ flex: 1, fontSize: 12, color: theme.textMuted }}>日期</Text>
                  <Text style={{ width: 88, fontSize: 12, color: theme.textMuted, textAlign: 'right' }}>净值</Text>
                  <Text style={{ width: 76, fontSize: 12, color: theme.textMuted, textAlign: 'right' }}>日涨幅</Text>
                </View>
                {recentNav.map((point) => (
                  <View
                    key={point.nav_date}
                    style={{
                      flexDirection: 'row',
                      alignItems: 'center',
                      paddingVertical: 9,
                      borderBottomWidth: 1,
                      borderColor: theme.border,
                    }}
                  >
                    <Text style={{ flex: 1, fontSize: 14, color: theme.text }}>{formatDate(point.nav_date)}</Text>
                    <Text style={{ width: 88, fontSize: 14, color: theme.text, textAlign: 'right' }}>
                      {formatNumber(point.unit_nav)}
                    </Text>
                    <Text style={{ width: 76, fontSize: 14, textAlign: 'right', color: trendColor(point.daily_return) }}>
                      {formatReturnPoints(point.daily_return)}
                    </Text>
                  </View>
                ))}
                {navPoints.length > NAV_ROWS_COLLAPSED ? (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="查看全部净值记录"
                    hitSlop={8}
                    onPress={() => router.push(`/nav-history?code=${code}`)}
                    style={({ pressed }) => [{ marginTop: 8, opacity: pressed ? 0.85 : 1 }]}
                  >
                    <Text style={{ fontSize: 13, color: theme.primary, textAlign: 'center' }}>查看净值详情</Text>
                  </Pressable>
                ) : null}
              </View>
            )
          }
        </Async>
      </Card>

      <Card>
        <SectionTitle title="我的持仓" action="修改持仓" onAction={() => router.push(`/position/edit?code=${code}&account_id=${accountId ?? ''}`)} />
        {/* 这个接口返回 404 只表示“当前视图下没有持仓”，并不是错误。 */}
        {position.isPending ? (
          <LoadingState />
        ) : position.data ? (
          <View>
            <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
              <Stat label="持有金额" value={formatMoney(position.data.market_value)} />
              <Stat label="持有份额" value={formatNumber(position.data.shares)} />
              <Stat label="持仓占比" value={formatRate(position.data.position_ratio)} />
              <Stat label="持有收益" value={formatSignedMoney(position.data.profit_loss)} tone={trendTone(position.data.profit_loss)} />
              <Stat label="持有收益率" value={formatRate(position.data.profit_loss_rate)} tone={trendTone(position.data.profit_loss_rate)} />
              <Stat label="持仓成本净值" value={formatNumber(position.data.average_cost_nav)} />
              <Stat label="昨日收益" value={formatSignedMoney(position.data.daily_profit_loss)} tone={trendTone(position.data.daily_profit_loss)} />
              <Stat label="首次购买" value={position.data.purchase_date ?? '--'} tone="muted" />
              <Stat
                label="持有天数"
                value={position.data.holding_days !== undefined && position.data.holding_days !== null ? `${position.data.holding_days}` : '--'}
                tone="muted"
              />
            </View>
            <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }}>
              成本 {formatMoney(position.data.cost_amount)} · 更新于 {formatDateTime(position.data.updated_at)}
            </Text>
          </View>
        ) : (
          <EmptyState title="还没有持仓" hint="点“修改持仓”手动录入一条" />
        )}
      </Card>

      <View style={{ flexDirection: 'row' }}>
        <View style={{ flex: 1, marginRight: 6 }}>
          <Button label="交易记录" variant="secondary" onPress={() => router.push(`/transactions?fund_code=${code}`)} />
        </View>
        <View style={{ flex: 1, marginLeft: 6 }}>
          <Button label={isWatchlisted ? '删除自选' : '加自选'} onPress={toggleWatchlist} loading={add.isPending || remove.isPending} />
        </View>
      </View>
      <View style={{ marginTop: 8 }}>
        <Button label="问小镜" variant="secondary" onPress={() => router.push(`/(tabs)/agent?fund_code=${code}`)} />
      </View>
      {notice ? (
        <Text
          style={{
            fontSize: 12,
            color: notice.error ? theme.danger : theme.primary,
            marginTop: 8,
            textAlign: 'center',
          }}
        >
          {notice.text}
        </Text>
      ) : null}

      <GroupPicker
        visible={pickingGroup}
        fundName={detail.data?.fund_name ?? code ?? ''}
        groups={groups.data?.items ?? []}
        busy={add.isPending}
        onCreateGroup={createGroupNamed}
        onCancel={() => setPickingGroup(false)}
        onConfirm={(groupIds) => {
          setPickingGroup(false);
          if (!code) return;
          add.mutate(
            { fund_code: code, group_ids: groupIds },
            {
              onSuccess: () =>
                setNotice({
                  text: groupIds.length > 0 ? `已加入自选与 ${groupIds.length} 个分组` : '已加入自选（不分组）',
                  error: false,
                }),
              onError: (error) => setNotice({ text: describeError(error), error: true }),
            },
          );
        }}
      />
    </Screen>
  );
}

function StarButton({ active, onPress }: { active: boolean; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={active ? '删除自选' : '加自选'}
      hitSlop={10}
      onPress={onPress}
      style={({ pressed }) => [{ paddingHorizontal: 16, opacity: pressed ? 0.7 : 1 }]}
    >
      <SymbolView
        name={{ ios: active ? 'star.fill' : 'star', android: active ? 'star' : 'star_border', web: active ? 'star' : 'star_border' }}
        tintColor={active ? theme.warning : theme.textMuted}
        size={22}
      />
    </Pressable>
  );
}

function trendTone(value: number | null | undefined): 'up' | 'down' | 'normal' {
  if (value === null || value === undefined || value === 0) return 'normal';
  return value > 0 ? 'up' : 'down';
}
