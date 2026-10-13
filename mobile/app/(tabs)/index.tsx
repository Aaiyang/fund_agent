import { Link, router } from 'expo-router';
import { useRef } from 'react';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, NavTab, Screen, SectionTitle } from '@/components/ui';
import { HoldingsTable } from '@/components/HoldingsTable';
import { theme } from '@/constants/theme';
import { useIndexQuotes } from '@/hooks/useIndexes';
import { navRefreshNotice, useNavRefreshOnFocus } from '@/hooks/useFunds';
import { useDragScroll } from '@/hooks/useDragScroll';
import {
  useAccounts,
  usePortfolioSummaries,
  usePortfolioSummary,
  usePositions,
  type AccountSummaryRow,
  type PortfolioSummary,
} from '@/hooks/usePortfolio';
import { estimatesByCode, useValuationEstimates } from '@/hooks/useValuation';
import { useUiStore } from '@/stores/ui';
import {
  formatMoney,
  formatNumber,
  formatRate,
  formatReturnPoints,
  formatSessionTime,
  formatSignedMoney,
  trendColor,
} from '@/utils/format';

export default function HoldingsScreen() {
  const accountId = useUiStore((state) => state.accountId);
  const setAccountId = useUiStore((state) => state.setAccountId);
  const accounts = useAccounts();
  const accountIds = (accounts.data?.items ?? []).map((account) => account.id);
  const summaries = usePortfolioSummaries(accountIds);
  // 合计走服务端那条跨账户汇总，不在前端把各账户相加（口径应当由后端定）。
  const total = usePortfolioSummary(null);
  const positions = usePositions(accountId);
  const valuations = useValuationEstimates((positions.data?.items ?? []).map((item) => item.fund_code));
  const quotes = useIndexQuotes();
  const nav = useNavRefreshOnFocus();
  const navNotice = navRefreshNotice(nav.isPending, nav.result);
  const tapeRef = useRef<ScrollView>(null);
  useDragScroll(tapeRef);
  const tape = (quotes.data?.items ?? []).map((index) => ({
    key: index.index_code,
    label: index.name,
    value: formatNumber(index.close, 2),
    change: formatReturnPoints(index.change_pct),
    tone: trendColor(index.change_pct),
  }));

  // 「账户汇总」看全部账户，各账户一张卡；选中某个账户时就只留那一张。
  const shown = accountId === null ? accountIds : accountIds.filter((id) => id === accountId);
  const rows: Record<number, AccountSummaryRow> = Object.fromEntries(
    (summaries.data ?? []).map((row) => [row.accountId, row]),
  );

  return (
    <Screen
      refreshing={summaries.isFetching || total.isFetching}
      onRefresh={() => void Promise.all([accounts.refetch(), summaries.refetch(), total.refetch(), positions.refetch()])}
      pinned={
        <View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <NavTab label="账户汇总" active={accountId === null} onPress={() => setAccountId(null)} />
            {(accounts.data?.items ?? []).map((account) => (
              <NavTab
                key={account.id}
                label={account.name}
                active={accountId === account.id}
                onPress={() => setAccountId(account.id)}
              />
            ))}
            <NavTab accent label="+ 添加账户" onPress={() => router.push('/account/add')} />
          </ScrollView>
          <ScrollView
            ref={tapeRef}
            horizontal
            showsHorizontalScrollIndicator={false}
            style={{ marginTop: 2 }}
          >
            {tape.map((entry) => (
              <Link key={entry.key} href={{ pathname: '/market/[symbol]', params: { symbol: entry.key } }} asChild>
                <Pressable
                  accessibilityRole="link"
                  accessibilityLabel={`查看${entry.label}走势`}
                  style={{ flexDirection: 'row', alignItems: 'baseline', marginRight: 16 }}
                >
                  <Text style={{ fontSize: 12, color: theme.textMuted }}>{entry.label}</Text>
                  {entry.value ? (
                    <Text style={{ fontSize: 13, color: theme.text, marginLeft: 5 }}>{entry.value}</Text>
                  ) : null}
                  <Text style={{ fontSize: 12, color: entry.tone, marginLeft: 5 }}>{entry.change}</Text>
                </Pressable>
              </Link>
            ))}
          </ScrollView>
        </View>
      }
    >
      {/* 汇总视图：先一张全部账户的合计卡（只读，点了没地方可去），再逐账户一张卡。 */}
      {accountId === null ? (
        <SummaryCard
          title="全部账户"
          stats={total.data?.summary ?? null}
          notice={navNotice}
          pending={total.isPending}
        />
      ) : null}

      {shown.map((id) => (
        <SummaryCard
          key={id}
          title={(accounts.data?.items ?? []).find((account) => account.id === id)?.name ?? `账户 #${id}`}
          stats={rows[id]?.summary ?? null}
          notice={navNotice}
          pending={summaries.isPending}
          failedNote={rows[id] ? '这个账户的汇总没取到，下拉可以重试' : null}
          onOpen={() => setAccountId(id)}
        />
      ))}

      {accountId === null && accounts.data?.items.length === 0 ? (
        <Card>
          <EmptyState title="还没有账户" hint="用上面那条「+ 添加账户」建一个，再录入或导入持仓" />
        </Card>
      ) : null}

      {/* 持仓明细属于单个账户：汇总视图下只给卡片，选到某个账户才列表。 */}
      {accountId === null ? null : (
        <Card>
          <SectionTitle title="持仓基金" action="导入持仓" onAction={() => router.push('/holding-import')} />
          <Async
            query={positions}
            empty={(data) =>
              data.items.length === 0 ? (
                <EmptyState title="还没有持仓" hint="点上方「导入持仓」上传截图，或手动录入一条" />
              ) : null
            }
          >
            {(data) => <HoldingsTable items={data.items} estimates={estimatesByCode(valuations.data?.items)} />}
          </Async>
        </Card>
      )}
    </Screen>
  );
}

/**
 * 资产卡：合计卡与单账户卡共用一套排版。
 *
 * 传 `onOpen` 才可点（点它是把自己切成"当前账户"，明细表随之在下方展开；
 * 不跳新页面，账户的增删改都在「我的 → 账户管理」）。合计卡不传，就是一张
 * 只读的数，免得点上去什么都没发生。
 *
 * 汇总按账户逐个取（后端没有跨账户的批量端点），某一只失败时这张卡自己说
 * "没取到"，不拿别的账户或零来充数。
 */
function SummaryCard({
  title,
  stats,
  notice,
  pending,
  failedNote,
  onOpen,
}: {
  title: string;
  stats: PortfolioSummary | null;
  notice: string | null;
  pending: boolean;
  failedNote?: string | null;
  onOpen?: () => void;
}) {
  const body = (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, flex: 1 }} numberOfLines={1}>
          {title}
        </Text>
        {onOpen ? <Text style={{ fontSize: 13, color: theme.primary }}>查看持仓</Text> : null}
      </View>
      <Text style={{ fontSize: 12, color: theme.textMuted }}>总资产（元）</Text>
      <Text style={{ fontSize: 30, fontWeight: '700', color: theme.text, marginVertical: 4 }}>
        {stats ? formatMoney(stats.total_market_value) : '--'}
      </Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
        <Metric label="昨日收益" value={stats ? formatSignedMoney(stats.daily_profit_loss) : '--'} color={trendColor(stats?.daily_profit_loss)} />
        <Metric label="累计收益" value={stats ? formatSignedMoney(stats.total_profit_loss) : '--'} color={trendColor(stats?.total_profit_loss)} />
        <Metric label="累计收益率" value={stats ? formatRate(stats.total_profit_loss_rate) : '--'} color={trendColor(stats?.total_profit_loss)} />
        <Metric label="持仓数量" value={stats ? `${stats.fund_count}` : '--'} color={theme.text} />
      </View>
      {/* 汇总卡属于列表式扫读场景，时间用紧凑相对口径（今天/昨天/月日），不铺全长日期。 */}
      <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 6 }}>
        {stats
          ? `数据更新：${formatSessionTime(stats.data_updated_at)}${notice ? ` · ${notice}` : ''}`
          : (failedNote ?? (pending ? '正在读汇总…' : '汇总没取到，下拉可以重试'))}
      </Text>
    </Card>
  );

  if (!onOpen) return body;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`切到${title}看持仓明细`}
      onPress={onOpen}
      style={({ pressed }) => [{ opacity: pressed ? 0.85 : 1 }]}
    >
      {body}
    </Pressable>
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
