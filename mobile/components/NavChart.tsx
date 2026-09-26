/**
 * Cumulative-return line chart: the fund plus an optional benchmark, both
 * indexed to +0% at the window start so one axis serves both.
 *
 * react-native-svg only — no charting dependency: the series is a few hundred
 * points at most and each shape is a single polyline. Points are placed on a
 * time axis, not by array index, because fund NAV days and index trading days
 * do not line up one for one.
 */

import { type ReactNode, useState } from 'react';
import { type GestureResponderEvent, Pressable, Text, View } from 'react-native';
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

export type BenchmarkPicker = {
  open: boolean;
  options: { value: string | null; label: string }[];
  selected: string | null;
  onToggle: () => void;
  onPick: (value: string | null) => void;
};

export function NavChart({
  points,
  benchmark,
  costNav,
  benchmarkPicker,
}: {
  points: FundPoint[];
  benchmark?: { name: string; points: BenchmarkPoint[] } | null;
  costNav?: number | null;
  /** When set, the legend's benchmark entry becomes the switcher's trigger. */
  benchmarkPicker?: BenchmarkPicker | null;
}) {
  const [width, setWidth] = useState(0);
  // The pinned day carries the window it was picked in: after a range switch
  // the stored date belongs to another series, so the crosshair drops itself.
  const [pinned, setPinned] = useState<{ window: string; label: string } | null>(null);
  const fund = toSeries(points, (point) => point.nav_date, (point) => point.unit_nav);
  const windowKey = `${points[0]?.nav_date ?? ''}:${points[points.length - 1]?.nav_date ?? ''}`;

  if (fund.length < 2) {
    return (
      <View style={{ height: HEIGHT, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: theme.textFaint, fontSize: 13 }}>净值数据不足，暂无法绘制走势</Text>
      </View>
    );
  }

  const fundBase = fund[0].value;
  const fundSeries = fund.map((point) => ({ ...point, change: (point.value / fundBase - 1) * 100 }));
  const windowStart = fund[0].time;
  const windowEnd = fund[fund.length - 1].time;

  // Trim the benchmark to the fund's own window and index it from the first
  // close inside it: a longer-lived index would otherwise start left of the
  // axis (clipped) and quote a change over a different period than the fund.
  const benchmarkWindow = toSeries(benchmark?.points ?? [], (point) => point.trade_date, (point) => point.close).filter(
    (point) => point.time >= windowStart && point.time <= windowEnd,
  );
  const benchmarkSeries =
    benchmarkWindow.length >= 2
      ? benchmarkWindow.map((point) => ({ ...point, change: (point.value / benchmarkWindow[0].value - 1) * 100 }))
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

  // A pressed day keeps the crosshair and the readout on that date; the legend
  // above mirrors it, so the pair stays in sync while the finger slides.
  const marker = pinned && pinned.window === windowKey ? fundSeries.find((point) => point.label === pinned.label) ?? null : null;
  const markerBenchmark = marker && benchmarkSeries.length ? nearestByTime(benchmarkSeries, marker.time) : null;
  const shownFundChange = marker ? marker.change : lastChange;
  const shownBenchmarkChange = marker && markerBenchmark ? markerBenchmark.change : benchmarkChange;

  const locate = (event: GestureResponderEvent) => {
    const locationX = event.nativeEvent.locationX;
    if (width <= 0 || locationX === undefined || locationX === null) return;
    const ratio = Math.min(Math.max(locationX / width, 0), 1);
    const nearest = nearestByTime(fundSeries, first.time + ratio * (last.time - first.time));
    setPinned({ window: windowKey, label: nearest.label });
  };

  // The date chip is a fixed-width box, so it is pulled back inside the plot
  // at both ends of the series instead of overrunning the card.
  const CHIP_W = 78;
  const markerX = marker ? x(marker.time) : 0;
  const chipLeft = marker ? Math.min(Math.max(markerX - CHIP_W / 2, 0), Math.max(width - CHIP_W, 0)) : 0;

  const pickerArrow = (
    <Text style={{ fontSize: 10, color: theme.textFaint, marginLeft: 3 }}>{benchmarkPicker?.open ? '▴' : '▾'}</Text>
  );
  const benchmarkLegend =
    benchmarkSeries.length && benchmark ? (
      <Legend color={theme.warning} label={benchmark.name} value={shownBenchmarkChange} trailing={pickerArrow} />
    ) : (
      <Text style={{ fontSize: 12, color: theme.textMuted, marginRight: 12 }}>选基准</Text>
    );

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      {/* Every RN-web View is its own stacking context (position:relative +
          z-index:0), so the open menu needs a rank here or the chart painted
          later in the tree swallows its taps. */}
      <View style={{ marginBottom: 6, zIndex: benchmarkPicker?.open ? 20 : 0 }}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' }}>
          <Legend color={theme.primary} label="本基金" value={shownFundChange} />
          {benchmarkPicker ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="切换比较基准"
              onPress={benchmarkPicker.onToggle}
              style={{ flexDirection: 'row', alignItems: 'center' }}
            >
              {benchmarkLegend}
            </Pressable>
          ) : (
            benchmarkSeries.length && benchmark ? benchmarkLegend : null
          )}
          {costChange !== null ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
              <Text style={{ fontSize: 12, color: theme.textFaint }}>成本价 {costNav?.toFixed(4)}</Text>
            </View>
          ) : null}
        </View>
        {benchmarkPicker?.open ? (
          <Pressable
            accessibilityLabel="关闭基准下拉"
            onPress={benchmarkPicker.onToggle}
            style={{ position: 'absolute', top: -600, left: -600, right: -600, bottom: -600, zIndex: 10 }}
          />
        ) : null}
        {benchmarkPicker?.open ? (
          <View
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              marginTop: 4,
              minWidth: 128,
              backgroundColor: theme.surface,
              borderRadius: 10,
              borderWidth: 1,
              borderColor: theme.border,
              paddingVertical: 4,
              zIndex: 20,
              elevation: 6,
            }}
          >
            {benchmarkPicker.options.map((option) => (
              <Pressable
                key={option.value ?? 'none'}
                accessibilityRole="menuitem"
                onPress={() => benchmarkPicker.onPick(option.value)}
                style={{ paddingHorizontal: 12, paddingVertical: 9 }}
              >
                <Text style={{ fontSize: 13, color: option.value === benchmarkPicker.selected ? theme.primary : theme.text }}>
                  {option.label}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </View>

      {width > 0 ? (
        <View
          accessibilityLabel="点选或左右拖动查看某日的累计涨跌幅"
          onStartShouldSetResponder={() => true}
          onMoveShouldSetResponder={() => true}
          onResponderTerminationRequest={() => false}
          onResponderGrant={locate}
          onResponderMove={locate}
        >
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
          {marker ? (
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                top: 0,
                left: chipLeft,
                width: CHIP_W,
                borderRadius: 4,
                backgroundColor: theme.surface,
                borderWidth: 1,
                borderColor: theme.border,
                paddingVertical: 2,
              }}
            >
              <Text style={{ fontSize: 10, color: theme.text, textAlign: 'center' }}>{formatDate(marker.label)}</Text>
            </View>
          ) : null}
        </View>
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

function Legend({
  color,
  label,
  value,
  trailing,
}: {
  color: string;
  label: string;
  value: number | null;
  /** Sits between the name and the figure, e.g. the picker's arrow. */
  trailing?: ReactNode;
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
      <View style={{ width: 12, height: 2, backgroundColor: color, marginRight: 5 }} />
      <Text style={{ fontSize: 12, color: theme.textMuted }}>{label}</Text>
      {trailing}
      <Text style={{ fontSize: 12, marginLeft: 4, color: (value ?? 0) >= 0 ? theme.up : theme.down }}>
        {value === null ? '--' : `${value > 0 ? '+' : ''}${value.toFixed(2)}%`}
      </Text>
    </View>
  );
}
