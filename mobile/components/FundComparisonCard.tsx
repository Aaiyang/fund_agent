/**
 * 多基金对比卡：归一收益/回撤曲线、报告时点数字表、共同窗口阶段收益热力表。
 *
 * 曲线按报告固定的共同窗口另取对齐序列；表格数字来自报告消息里的引用，
 * 避免曲线随查询更新后与报告里的区间收益/回撤对不上。
 */

import { useState } from 'react';
import { Text, View } from 'react-native';

import type { components } from '@/api/schema';
import { ComparisonChart, COMPARISON_COLORS, type ComparisonSeries } from '@/components/ComparisonChart';
import { Async, EmptyState } from '@/components/states';
import { Badge, Card, Chip, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useFundComparisonNav, type FundComparisonChartRef } from '@/hooks/useFunds';
import { formatDate, formatRate, formatSignedRate } from '@/utils/format';

type ChartFund = components['schemas']['FundComparisonChartFund'];
type SeriesFund = components['schemas']['FundComparisonSeriesFund'];
type PeriodKey = 'return_1m' | 'return_3m' | 'return_6m' | 'return_1y';

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: 'return_1m', label: '1月' },
  { key: 'return_3m', label: '3月' },
  { key: 'return_6m', label: '6月' },
  { key: 'return_1y', label: '1年' },
];

function Metric({ label, value, tone }: { label: string; value: string; tone: 'up' | 'down' | 'muted' }) {
  const color = value === '--' ? theme.textFaint : tone === 'up' ? theme.up : tone === 'down' ? theme.down : theme.textMuted;
  return (
    <View style={{ flex: 1, minWidth: 0 }}>
      <Text style={{ fontSize: 10, color: theme.textFaint, marginBottom: 3 }}>{label}</Text>
      <Text style={{ fontSize: 13, fontWeight: '600', color }} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function ComparisonTable({ funds, names }: { funds: ChartFund[]; names: Map<string, string | null | undefined> }) {
  return (
    <View style={{ marginTop: 12 }}>
      {funds.map((fund, index) => (
        <View
          key={fund.fund_code}
          style={{
            paddingTop: 10,
            marginTop: index === 0 ? 0 : 4,
            borderTopWidth: index === 0 ? 0 : 1,
            borderTopColor: theme.border,
          }}
        >
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: COMPARISON_COLORS[index % COMPARISON_COLORS.length] }} />
            <Text numberOfLines={1} style={{ flexShrink: 1, marginLeft: 6, fontSize: 13, fontWeight: '600', color: theme.text }}>
              {names.get(fund.fund_code) || fund.fund_code}
            </Text>
            <Text style={{ marginLeft: 6, fontSize: 11, color: theme.textFaint }}>{fund.fund_code}</Text>
            {fund.stale ? <View style={{ marginLeft: 8 }}><Badge label="数据可能不是最新" tone="warning" /></View> : null}
          </View>
          <View style={{ flexDirection: 'row', marginTop: 8, gap: 6 }}>
            <Metric
              label="区间收益"
              value={formatSignedRate(fund.window_change_ratio)}
              tone={(fund.window_change_ratio ?? 0) > 0 ? 'up' : (fund.window_change_ratio ?? 0) < 0 ? 'down' : 'muted'}
            />
            <Metric label="最大回撤" value={formatSignedRate(fund.observed_max_drawdown_ratio)} tone="down" />
            <Metric label="年化波动" value={formatRate(fund.annualized_nav_volatility_ratio)} tone="muted" />
            <Metric label="样本" value={`${fund.aligned_count ?? 0} 天`} tone="muted" />
          </View>
        </View>
      ))}
    </View>
  );
}

/** 热力色只做强弱提示，具体数值仍以文字为准；0 和缺失不染色. */
function heatTint(value: number | null | undefined): string {
  if (value == null || value === 0) return theme.surfaceSoft;
  const intensity = Math.min(0.2, 0.06 + Math.abs(value) * 0.35);
  return value > 0 ? `rgba(196, 61, 50, ${intensity})` : `rgba(46, 118, 84, ${intensity})`;
}

function PeriodHeatmap({ funds, names }: { funds: SeriesFund[]; names: Map<string, string | null | undefined> }) {
  if (!funds.length) return null;
  return (
    <View style={{ marginTop: 12 }}>
      <Text style={{ fontSize: 12, fontWeight: '600', color: theme.text, marginBottom: 6 }}>阶段收益（共同窗口内）</Text>
      <View style={{ flexDirection: 'row', paddingBottom: 5, borderBottomWidth: 1, borderBottomColor: theme.border }}>
        <View style={{ width: 12 }} />
        <Text style={{ flex: 1.4, fontSize: 10, color: theme.textFaint }}>基金</Text>
        {PERIODS.map((period) => (
          <Text key={period.key} style={{ flex: 1, fontSize: 10, color: theme.textFaint, textAlign: 'center' }}>{period.label}</Text>
        ))}
      </View>
      {funds.map((fund, index) => (
        <View key={fund.fund_code} style={{ flexDirection: 'row', alignItems: 'center', paddingTop: 6 }}>
          <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: COMPARISON_COLORS[index % COMPARISON_COLORS.length] }} />
          <Text numberOfLines={1} style={{ flex: 1.4, marginLeft: 5, fontSize: 11, color: theme.text }}>
            {names.get(fund.fund_code) || fund.fund_code}
          </Text>
          {PERIODS.map((period) => {
            const value = fund.period_returns?.[period.key] ?? null;
            return (
              <View
                key={period.key}
                style={{ flex: 1, marginLeft: 3, borderRadius: 6, paddingVertical: 6, alignItems: 'center', backgroundColor: heatTint(value) }}
              >
                <Text style={{ fontSize: 11, fontWeight: '600', color: value == null || value === 0 ? theme.textMuted : value > 0 ? theme.up : theme.down }}>
                  {formatSignedRate(value)}
                </Text>
              </View>
            );
          })}
        </View>
      ))}
      <Text style={{ fontSize: 10, lineHeight: 16, color: theme.textFaint, marginTop: 6 }}>
        红涨绿跌；按图表共同窗口内的阶段收益计算，窗口不足显示 --。
      </Text>
    </View>
  );
}

export function FundComparisonCard({ chart }: { chart: FundComparisonChartRef }) {
  const query = useFundComparisonNav(chart);
  const [mode, setMode] = useState<'return' | 'drawdown'>('return');
  const funds = chart.funds ?? [];
  if (funds.length < 2) return null;
  const byCode = new Map((query.data?.funds ?? []).map((fund) => [fund.fund_code, fund]));
  const seriesFunds: SeriesFund[] = chart.fund_codes.flatMap((code) => {
    const fund = byCode.get(code);
    return fund ? [fund] : [];
  });
  const names = new Map(seriesFunds.map((fund) => [fund.fund_code, fund.fund_name]));
  const series: ComparisonSeries[] = seriesFunds.map((fund) => ({
    fund_code: fund.fund_code,
    fund_name: fund.fund_name,
    points: fund.points ?? [],
  }));
  const missingDrawdown = funds.filter((fund) => fund.observed_max_drawdown_ratio == null).map((fund) => fund.fund_code);
  const drawdownSeries = series.filter((fund) => !missingDrawdown.includes(fund.fund_code));
  const chartSeries = mode === 'drawdown' ? drawdownSeries : series;

  return (
    <Card>
      <SectionTitle title="同期收益对比" />
      <Text style={{ fontSize: 11, color: theme.textFaint, marginBottom: 8 }}>
        共同窗口 {formatDate(chart.common_from)} 至 {formatDate(chart.common_to)} · {chart.aligned_count ?? 0} 个交易日
      </Text>
      <View style={{ flexDirection: 'row' }}>
        <Chip label="累计收益" active={mode === 'return'} onPress={() => setMode('return')} />
        <Chip label="回撤" active={mode === 'drawdown'} onPress={() => setMode('drawdown')} />
      </View>
      <Async
        query={query}
        empty={(data) =>
          (data.funds ?? []).filter((fund) => (fund.points?.length ?? 0) >= 2).length < 2
            ? <EmptyState title="没有可绘制的共同净值" hint={data.gaps?.[0] ?? '两只基金没有足够的共同交易日。'} />
            : null
        }
      >
        {() => {
          if (mode === 'drawdown' && !drawdownSeries.length) {
            return (
              <View style={{ paddingVertical: 18, alignItems: 'center' }}>
                <Text style={{ fontSize: 13, color: theme.textMuted }}>同窗口回撤都没有算出，暂不能绘制回撤曲线。切回累计收益查看收益对比。</Text>
              </View>
            );
          }
          return (
            <ComparisonChart
              key={`${chart.fund_codes.join(',')}:${chart.common_from}:${chart.common_to}:${query.data?.aligned_count ?? 0}:${mode}`}
              funds={chartSeries}
              mode={mode}
              minFunds={mode === 'drawdown' ? 1 : 2}
            />
          );
        }}
      </Async>
      {mode === 'drawdown' && missingDrawdown.length ? (
        <Text style={{ fontSize: 11, color: theme.warning, marginTop: 4 }}>
          未绘制 {missingDrawdown.join('、')}：同窗口回撤未算出。
        </Text>
      ) : null}
      <ComparisonTable funds={funds} names={names} />
      {query.data ? <PeriodHeatmap funds={seriesFunds} names={names} /> : null}
      <Text style={{ fontSize: 11, lineHeight: 17, color: theme.textFaint, marginTop: 8 }}>
        {mode === 'drawdown'
          ? '回撤曲线为相对共同窗口内各自高点的当期回撤；数字表的「最大回撤」是窗口最低点。未算出的基金不绘制。'
          : '曲线以共同窗口首个共同净值为 0% 定基；未复权单位净值。数字表为报告时点指标，阶段收益按图表窗口重算。'}
      </Text>
    </Card>
  );
}
