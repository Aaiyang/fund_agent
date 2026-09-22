/**
 * Cumulative-return line chart: the fund plus an optional benchmark, both
 * indexed to +0% at the window start so one axis serves both.
 *
 * react-native-svg only — no charting dependency: the series is a few hundred
 * points at most and each shape is a single polyline. Points are placed on a
 * time axis, not by array index, because fund NAV days and index trading days
 * do not line up one for one.
 */

import { useState } from 'react';
import { Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate } from '@/utils/format';

type FundPoint = { nav_date: string; unit_nav?: number | null };
type BenchmarkPoint = { trade_date: string; close?: number | null };

const HEIGHT = 180;
const PADDING = 6;

function toSeries<T>(points: T[], dateOf: (point: T) => string, valueOf: (point: T) => number | null | undefined) {
  return points
    .map((point) => ({ time: Date.parse(dateOf(point)), value: valueOf(point) }))
    .filter((entry): entry is { time: number; value: number } => Number.isFinite(entry.time) && entry.value !== null && entry.value !== undefined);
}

export function NavChart({
  points,
  benchmark,
  costNav,
}: {
  points: FundPoint[];
  benchmark?: { name: string; points: BenchmarkPoint[] } | null;
  costNav?: number | null;
}) {
  const [width, setWidth] = useState(0);
  const fund = toSeries(points, (point) => point.nav_date, (point) => point.unit_nav);

  if (fund.length < 2) {
    return (
      <View style={{ height: HEIGHT, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: theme.textFaint, fontSize: 13 }}>净值数据不足，暂无法绘制走势</Text>
      </View>
    );
  }

  const fundBase = fund[0].value;
  const fundSeries = fund.map((point) => ({ ...point, change: (point.value / fundBase - 1) * 100 }));

  const benchmarkRaw = toSeries(benchmark?.points ?? [], (point) => point.trade_date, (point) => point.close);
  const benchmarkSeries =
    benchmarkRaw.length >= 2
      ? benchmarkRaw.map((point) => ({ ...point, change: (point.value / benchmarkRaw[0].value - 1) * 100 }))
      : [];

  const costChange = costNav && costNav > 0 ? (costNav / fundBase - 1) * 100 : null;
  const changes = [...fundSeries, ...benchmarkSeries].map((point) => point.change);
  if (costChange !== null) changes.push(costChange);
  const min = Math.min(...changes, 0);
  const max = Math.max(...changes, 0);
  const span = max - min || 1;

  const first = fundSeries[0];
  const last = fundSeries[fundSeries.length - 1];
  const x = (time: number) => ((time - first.time) / (last.time - first.time || 1)) * width;
  const y = (change: number) => HEIGHT - PADDING - ((change - min) / span) * (HEIGHT - PADDING * 2);
  const path = (series: { time: number; change: number }[]) =>
    series.map((point) => `${x(point.time).toFixed(2)},${y(point.change).toFixed(2)}`).join(' ');

  const lastChange = last.change;
  const benchmarkChange = benchmarkSeries.length ? benchmarkSeries[benchmarkSeries.length - 1].change : null;

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 6 }}>
        <Legend color={theme.primary} label="本基金" value={lastChange} />
        {benchmarkSeries.length && benchmark ? <Legend color={theme.warning} label={benchmark.name} value={benchmarkChange} /> : null}
        {costChange !== null ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
            <Text style={{ fontSize: 12, color: theme.textFaint }}>成本价 {costNav?.toFixed(4)}</Text>
          </View>
        ) : null}
      </View>

      {width > 0 ? (
        <Svg width={width} height={HEIGHT}>
          <Line x1={0} y1={y(0)} x2={width} y2={y(0)} stroke={theme.border} strokeWidth={1} />
          {costChange !== null ? (
            <Line
              x1={0}
              y1={y(costChange)}
              x2={width}
              y2={y(costChange)}
              stroke={theme.textFaint}
              strokeWidth={1}
              strokeDasharray="5,4"
            />
          ) : null}
          {benchmarkSeries.length ? (
            <Polyline points={path(benchmarkSeries)} fill="none" stroke={theme.warning} strokeWidth={1.5} />
          ) : null}
          <Polyline points={path(fundSeries)} fill="none" stroke={theme.primary} strokeWidth={2} />
          <Circle cx={x(last.time)} cy={y(lastChange)} r={3} fill={lastChange >= 0 ? theme.up : theme.down} />
        </Svg>
      ) : (
        <View style={{ height: HEIGHT }} />
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(points[0].nav_date)}</Text>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>
          {`${min.toFixed(2)}% ~ ${max.toFixed(2)}%`}
        </Text>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(points[points.length - 1].nav_date)}</Text>
      </View>
    </View>
  );
}

function Legend({ color, label, value }: { color: string; label: string; value: number | null }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
      <View style={{ width: 12, height: 2, backgroundColor: color, marginRight: 5 }} />
      <Text style={{ fontSize: 12, color: theme.textMuted }}>{label}</Text>
      <Text style={{ fontSize: 12, marginLeft: 4, color: (value ?? 0) >= 0 ? theme.up : theme.down }}>
        {value === null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`}
      </Text>
    </View>
  );
}
