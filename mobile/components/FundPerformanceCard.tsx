import { useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import { NavChart } from '@/components/NavChart';
import { Async, EmptyState, ErrorState, describeError } from '@/components/states';
import { Card, Chip, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { NAV_RANGES, useFundDetail, useFundNav, type NavRange } from '@/hooks/useFunds';
import { DEFAULT_BENCHMARK, useIndexCatalog, useIndexHistory } from '@/hooks/useIndexes';
import { formatDate, formatRate } from '@/utils/format';

/** 只给小镜的回答用的数据适配器：复用现有的 NavChart，不去改基金详情页。 */
export function FundPerformanceCard({ fundCode }: { fundCode: string }) {
  const [range, setRange] = useState<NavRange>('1y');
  const [benchmarkCode, setBenchmarkCode] = useState<string | null>(DEFAULT_BENCHMARK);
  const [pickingBenchmark, setPickingBenchmark] = useState(false);
  const code = /^\d{6}$/.test(fundCode) ? fundCode : null;
  const detail = useFundDetail(code);
  const nav = useFundNav(code, range);
  const benchmark = useIndexHistory(code ? benchmarkCode : null, range);
  const catalog = useIndexCatalog();
  const performance = detail.data?.performance;

  return (
    <Card>
      <SectionTitle title="业绩走势" />
      <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 8 }}>
        {detail.data?.fund_name ?? fundCode} · {fundCode}
      </Text>
      <Async query={nav}>
        {(data) =>
          data.points.length === 0 ? (
            <EmptyState title="还没有净值数据" hint="换个基金代码，或稍后重新问小镜" />
          ) : (
            <>
              <NavChart
                key={`${fundCode}:${range}`}
                points={data.points}
                benchmark={benchmark.data && benchmarkCode ? { name: benchmark.data.name, points: benchmark.data.points } : null}
                benchmarkPicker={{
                  open: pickingBenchmark,
                  options: (catalog.data?.items ?? []).map((item) => ({ value: item.index_code, label: item.name })),
                  selected: benchmarkCode,
                  onToggle: () => setPickingBenchmark((open) => !open),
                  onPick: (value) => { setBenchmarkCode(value); setPickingBenchmark(false); },
                }}
              />
              <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 6 }}>
                实际区间 {formatDate(data.points[0]?.nav_date)} 至 {formatDate(data.points[data.points.length - 1]?.nav_date)}
              </Text>
            </>
          )
        }
      </Async>
      {benchmark.isPending && code ? <Text style={{ fontSize: 11, color: theme.textMuted }}>比较基准加载中…</Text> : null}
      {benchmark.isError ? <ErrorState message={`比较基准：${describeError(benchmark.error)}`} onRetry={() => void benchmark.refetch()} /> : null}
      {catalog.isError ? <ErrorState message={`基准目录：${describeError(catalog.error)}`} onRetry={() => void catalog.refetch()} /> : null}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
        {NAV_RANGES.map((item) => <Chip
          key={item.key} label={item.label} active={range === item.key}
          onPress={() => setRange(item.key)}
        />)}
      </ScrollView>
      {performance ? <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
        {([
          ['近 1 月', performance.return_1m], ['近 3 月', performance.return_3m],
          ['近 6 月', performance.return_6m], ['近 1 年', performance.return_1y],
          ['近 3 年', performance.return_3y], ['成立以来', performance.return_since_inception],
        ] as const).map(([label, value]) => <Stat key={label} label={label} value={formatRate(value)} tone={trendTone(value)} />)}
        <Stat label="最大回撤" value={formatRate(performance.max_drawdown)} tone="down" />
        <Stat label="年化波动率" value={formatRate(performance.annualized_volatility)} tone="muted" />
      </View> : detail.isPending ? <Text style={{ fontSize: 11, color: theme.textMuted }}>业绩指标加载中…</Text> : null}
      {detail.isError ? <ErrorState message={`业绩指标：${describeError(detail.error)}`} onRetry={() => void detail.refetch()} /> : null}
      <Text style={{ fontSize: 11, lineHeight: 17, color: theme.textFaint, marginTop: 6 }}>
        单位净值变化，未做分红复权，不代表含分红总回报。指标截至 {formatDate(detail.data?.nav_date)}；图表随查询更新，可能与回答时的数据日期不同。
      </Text>
    </Card>
  );
}

function trendTone(value: number | null | undefined): 'up' | 'down' | 'normal' {
  if (value === null || value === undefined || value === 0) return 'normal';
  return value > 0 ? 'up' : 'down';
}
