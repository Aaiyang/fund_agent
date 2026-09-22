import { Stack, router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
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

const NAV_ROWS_COLLAPSED = 10;

/** Fund detail: overview + holdings context + NAV chart (spec 3.5). */
export default function FundDetailScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const [range, setRange] = useState<NavRange>('1y');
  const [benchmarkCode, setBenchmarkCode] = useState<string | null>(DEFAULT_BENCHMARK);
  const [pickingBenchmark, setPickingBenchmark] = useState(false);
  const [showAllNav, setShowAllNav] = useState(false);
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
  const [notice, setNotice] = useState<string | null>(null);
  const [pickingGroup, setPickingGroup] = useState(false);

  const isWatchlisted = (watchlist.data?.items ?? []).some((item) => item.fund_code === code);

  function toggleWatchlist() {
    if (!code) return;
    setNotice(null);
    if (isWatchlisted) {
      remove.mutate(code, { onError: (error) => setNotice(error.message) });
      return;
    }
    // Adding is never silent: the caller picks groups, or 不分组, first (spec 3.3).
    setPickingGroup(true);
  }

  async function createGroupNamed(name: string): Promise<number | null> {
    try {
      const group = await createGroup.mutateAsync({ name });
      return group.id;
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '分组创建失败');
      return null;
    }
  }

  const navPoints = nav.data?.points ?? [];
  const recentNav = showAllNav ? navPoints : navPoints.slice(-NAV_ROWS_COLLAPSED);

  return (
    <Screen>
      <Stack.Screen options={{ headerRight: () => <StarButton active={isWatchlisted} onPress={toggleWatchlist} /> }} />

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

          <View style={{ flexDirection: 'row', alignItems: 'baseline', marginTop: 14 }}>
            <Text style={{ fontSize: 32, fontWeight: '700', color: trendColor(detail.data.daily_return) }}>
              {formatReturnPoints(detail.data.daily_return)}
            </Text>
            <Text style={{ fontSize: 12, color: theme.textFaint, marginLeft: 8 }}>
              {formatDate(detail.data.nav_date)}
            </Text>
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'baseline', marginTop: 2 }}>
            <Text style={{ fontSize: 13, color: theme.textMuted }}>单位净值</Text>
            <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginLeft: 6 }}>
              {formatNumber(detail.data.latest_nav)}
            </Text>
            <Text style={{ fontSize: 13, color: theme.textMuted, marginLeft: 14 }}>累计净值</Text>
            <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginLeft: 6 }}>
              {formatNumber(detail.data.accumulated_nav)}
            </Text>
          </View>

          <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 12 }}>
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
          <Pressable
            accessibilityRole="button"
            onPress={() => setPickingBenchmark(true)}
            style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}
          >
            <View style={{ width: 12, height: 2, backgroundColor: theme.warning, marginRight: 5 }} />
            <Text style={{ fontSize: 13, color: theme.text }}>
              业绩比较基准：{catalog.data?.items.find((item) => item.index_code === benchmarkCode)?.name ?? '不比较'}
            </Text>
            <Text style={{ fontSize: 12, color: theme.textFaint, marginLeft: 4 }}>▾</Text>
          </Pressable>
          <Async query={nav}>
            {(data) => (
              <NavChart
                points={data.points}
                benchmark={
                  benchmarkCode && benchmark.data
                    ? { name: benchmark.data.name, points: benchmark.data.points }
                    : null
                }
                costNav={position.data?.average_cost_nav ?? null}
              />
            )}
          </Async>
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
        <SectionTitle title="净值明细" />
        <Async query={nav}>
          {(data) =>
            data.points.length === 0 ? (
              <EmptyState title="还没有净值记录" hint="点“同步净值”拉取历史" />
            ) : (
              <View>
                <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.border, paddingBottom: 6 }}>
                  <Text style={{ flex: 1, fontSize: 12, color: theme.textMuted }}>日期</Text>
                  <Text style={{ width: 88, fontSize: 12, color: theme.textMuted }}>净值</Text>
                  <Text style={{ width: 76, fontSize: 12, color: theme.textMuted, textAlign: 'right' }}>日涨幅</Text>
                </View>
                {recentNav.map((point) => (
                  <View
                    key={point.nav_date}
                    style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 9, borderBottomWidth: 1, borderColor: theme.border }}
                  >
                    <Text style={{ flex: 1, fontSize: 14, color: theme.text }}>{formatDate(point.nav_date)}</Text>
                    <Text style={{ width: 88, fontSize: 14, color: theme.text }}>{formatNumber(point.unit_nav)}</Text>
                    <Text style={{ width: 76, fontSize: 14, textAlign: 'right', color: trendColor(point.daily_return) }}>
                      {formatReturnPoints(point.daily_return)}
                    </Text>
                  </View>
                ))}
                {data.points.length > NAV_ROWS_COLLAPSED ? (
                  <Pressable accessibilityRole="button" onPress={() => setShowAllNav((current) => !current)} style={{ marginTop: 10 }}>
                    <Text style={{ fontSize: 13, color: theme.primary, textAlign: 'center' }}>
                      {showAllNav ? '收起' : `查看全部 ${data.points.length} 条`}
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            )
          }
        </Async>
      </Card>

      <Card>
        <SectionTitle title="我的持仓" action="修改持仓" onAction={() => router.push(`/position/edit?code=${code}&account_id=${accountId ?? ''}`)} />
        {/* A 404 from this endpoint means "no position in the current view", not an error. */}
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
              <Stat label="当日收益" value={formatSignedMoney(position.data.daily_profit_loss)} tone={trendTone(position.data.daily_profit_loss)} />
              <Stat
                label="持有天数"
                value={position.data.holding_days !== undefined && position.data.holding_days !== null ? `${position.data.holding_days}` : '--'}
                tone="muted"
              />
            </View>
            <Text style={{ fontSize: 11, color: theme.textFaint }}>
              成本 {formatMoney(position.data.cost_amount)} · 更新于 {formatDateTime(position.data.updated_at)} · 版本 v
              {position.data.version}
            </Text>
          </View>
        ) : (
          <EmptyState title="该账户未持有此基金" hint="可点击“修改持仓”手动录入" />
        )}
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
      {notice ? (
        <Text style={{ fontSize: 12, color: theme.primary, marginTop: 10, textAlign: 'center' }}>{notice}</Text>
      ) : null}

      <BenchmarkPicker
        visible={pickingBenchmark}
        items={catalog.data?.items ?? []}
        selected={benchmarkCode}
        onCancel={() => setPickingBenchmark(false)}
        onPick={(indexCode) => {
          setBenchmarkCode(indexCode);
          setPickingBenchmark(false);
        }}
      />

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
              onSuccess: () => setNotice(groupIds.length > 0 ? `已加入自选与 ${groupIds.length} 个分组` : '已加入自选（不分组）'),
              onError: (error) => setNotice(error.message),
            },
          );
        }}
      />
    </Screen>
  );
}

function StarButton({ active, onPress }: { active: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={active ? '删除自选' : '加自选'} hitSlop={12} onPress={onPress} style={{ paddingHorizontal: 16 }}>
      <SymbolView
        name={{ ios: active ? 'star.fill' : 'star', android: active ? 'star' : 'star_border', web: active ? 'star' : 'star_border' }}
        tintColor={active ? theme.warning : theme.textMuted}
        size={22}
      />
    </Pressable>
  );
}

function BenchmarkPicker({
  visible,
  items,
  selected,
  onCancel,
  onPick,
}: {
  visible: boolean;
  items: { index_code: string; name: string }[];
  selected: string | null;
  onCancel: () => void;
  onPick: (indexCode: string | null) => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable accessibilityRole="button" onPress={onCancel} style={{ flex: 1, backgroundColor: '#00000066', justifyContent: 'center' }}>
        <View style={{ backgroundColor: theme.surface, marginHorizontal: 28, borderRadius: theme.radius, padding: theme.gap }}>
          <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginBottom: 10 }}>选择比较基准</Text>
          <ScrollView style={{ maxHeight: 320 }}>
            {items.map((item) => (
              <Pressable
                key={item.index_code}
                accessibilityRole="button"
                onPress={() => onPick(item.index_code)}
                style={{ paddingVertical: 12, borderBottomWidth: 1, borderColor: theme.border }}
              >
                <Text style={{ fontSize: 15, color: selected === item.index_code ? theme.primary : theme.text }}>{item.name}</Text>
              </Pressable>
            ))}
            <Pressable accessibilityRole="button" onPress={() => onPick(null)} style={{ paddingVertical: 12 }}>
              <Text style={{ fontSize: 15, color: selected === null ? theme.primary : theme.textMuted }}>不比较</Text>
            </Pressable>
          </ScrollView>
          <View style={{ marginTop: 8 }}>
            <Button label="取消" variant="secondary" onPress={onCancel} />
          </View>
        </View>
      </Pressable>
    </Modal>
  );
}

function trendTone(value: number | null | undefined): 'up' | 'down' | 'normal' {
  if (value === null || value === undefined || value === 0) return 'normal';
  return value > 0 ? 'up' : 'down';
}
