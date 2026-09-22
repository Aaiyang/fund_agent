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
import { Pressable, Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate } from '@/utils/format';

type FundPoint = { nav_date: string; unit_nav?: number | null };
type BenchmarkPoint = { trade_date: string; close?: number | null };

const HEIGHT = 180;
const PADDING = 6;

function toSeries<T>(points: T[], dateOf: (point: T) => string, valueOf: (point: T) => number | null | undefined) {
  return points
    .map((point) => ({ time: Date.parse(dateOf(point)), label: dateOf(point), value: valueOf(point) }))
    .filter((entry): entry is { time: number; label: string; value: number } => Number.isFinite(entry.time) && entry.value !== null && entry.value !== undefined);
}

/** Closest entry to `target` on the time axis. */
function nearestByTime<T extends { time: number }>(series: T[], target: number): T {
  return series.reduce((best, item) => (Math.abs(item.time - target) < Math.abs(best.time - target) ? item : best));
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
  const [markerLabel, setMarkerLabel] = useState<string | null>(null);
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

  // A tapped day keeps the crosshair and the readout on that date; tapping the
  // same day again clears it. Keyed by date so a range change cannot dangle.
  const marker = markerLabel ? fundSeries.find((point) => point.label === markerLabel) ?? null : null;
  const markerBenchmark = marker && benchmarkSeries.length ? nearestByTime(benchmarkSeries, marker.time) : null;
  const shownFundChange = marker ? marker.change : lastChange;
  const shownBenchmarkChange = marker && markerBenchmark ? markerBenchmark.change : benchmarkChange;

  const locate = (locationX: number) => {
    if (width <= 0) return;
    const ratio = Math.min(Math.max(locationX / width, 0), 1);
    const nearest = nearestByTime(fundSeries, first.time + ratio * (last.time - first.time));
    setMarkerLabel(nearest.label === markerLabel ? null : nearest.label);
  };

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 6 }}>
        <Legend color={theme.primary} label="本基金" value={shownFundChange} />
        {benchmarkSeries.length && benchmark ? <Legend color={theme.warning} label={benchmark.name} value={shownBenchmarkChange} /> : null}
        {costChange !== null ? (
          <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
            <Text style={{ fontSize: 12, color: theme.textFaint }}>成本价 {costNav?.toFixed(4)}</Text>
          </View>
        ) : null}
      </View>

      {width > 0 ? (
        <Pressable accessibilityLabel="点选某日查看当日累计涨跌幅" onPress={(event) => locate(event.nativeEvent.locationX ?? 0)}>
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
            {marker ? (
              <Line
                x1={x(marker.time)}
                y1={0}
                x2={x(marker.time)}
                y2={HEIGHT}
                stroke={theme.textMuted}
                strokeWidth={1}
                strokeDasharray="3,3"
              />
            ) : null}
            {marker && markerBenchmark ? (
              <Circle cx={x(markerBenchmark.time)} cy={y(markerBenchmark.change)} r={3.5} fill={theme.warning} />
            ) : null}
            {marker ? (
              <Circle cx={x(marker.time)} cy={y(marker.change)} r={3.5} fill={theme.primary} />
            ) : (
              <Circle cx={x(last.time)} cy={y(lastChange)} r={3} fill={lastChange >= 0 ? theme.up : theme.down} />
            )}
          </Svg>
        </Pressable>
      ) : (
        <View style={{ height: HEIGHT }} />
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(points[0].nav_date)}</Text>
        <Text style={{ fontSize: 11, color: marker ? theme.text : theme.textFaint }}>
          {marker ? formatDate(marker.label) : `${min.toFixed(2)}% ~ ${max.toFixed(2)}%`}
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
