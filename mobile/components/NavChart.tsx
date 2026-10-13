/**
 * 累计收益折线图：本基金加可选的业绩比较基准，两条曲线都以窗口起点为
 * +0% 定基，同一根坐标轴就能直接对比。
 *
 * 只用 react-native-svg、不引图表库：序列至多几百个点，每条形状就是一根
 * polyline。点按时间轴落位而不用数组下标，因为基金的净值日期和指数的
 * 交易日本来就不是一一对齐的。
 */

import { type ReactNode, useState } from 'react';
import { type GestureResponderEvent, Pressable, Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate, formatReturnPoints, trendColor } from '@/utils/format';

type FundPoint = { nav_date: string; unit_nav?: number | null };
type BenchmarkPoint = { trade_date: string; close?: number | null };

const HEIGHT = 180;
const PADDING = 6;

function toSeries<T>(points: T[], dateOf: (point: T) => string, valueOf: (point: T) => number | null | undefined) {
  return points
    .map((point) => ({ time: Date.parse(dateOf(point)), label: dateOf(point), value: valueOf(point) }))
    .filter((entry): entry is { time: number; label: string; value: number } => Number.isFinite(entry.time) && entry.value !== null && entry.value !== undefined);
}

/** 时间轴上离 `target` 最近的那个点。 */
function nearestByTime<T extends { time: number }>(series: T[], target: number): T {
  return series.reduce((best, item) => (Math.abs(item.time - target) < Math.abs(best.time - target) ? item : best));
}

export type BenchmarkPicker = {
  open: boolean;
  options: { value: string; label: string }[];
  selected: string | null;
  onToggle: () => void;
  onPick: (value: string) => void;
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
  /** 传入后，图例里的基准项就变成切换下拉的触发按钮。 */
  benchmarkPicker?: BenchmarkPicker | null;
}) {
  const [width, setWidth] = useState(0);
  // 钉住的日期记着它是在哪个窗口里选中的：切换区间后，存下的日期已属
  // 另一条序列，十字光标便自行作废。
  const [pinned, setPinned] = useState<{ window: string; label: string } | null>(null);
  const fund = toSeries(points, (point) => point.nav_date, (point) => point.unit_nav);
  const windowKey = `${points[0]?.nav_date ?? ''}:${points[points.length - 1]?.nav_date ?? ''}`;

  if (fund.length < 2) {
    return (
      <View style={{ height: HEIGHT, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: theme.textMuted, fontSize: 14 }}>还没有足够的净值数据，等净值更新后再看</Text>
      </View>
    );
  }

  const fundBase = fund[0].value;
  const fundSeries = fund.map((point) => ({ ...point, change: (point.value / fundBase - 1) * 100 }));
  const windowStart = fund[0].time;
  const windowEnd = fund[fund.length - 1].time;

  // 把基准裁剪到基金自己的窗口，并以窗口内第一根收盘定基：历史更长的
  // 指数否则会从头轴左侧开始（被裁掉），
  // 涨跌幅还算成了与基金不同的区间。
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

  // 按下某天就把十字光标和读数定在那一天；上方图例同步镜像它，
  // 手指滑动过程中两边始终对得上。
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

  // 日期贴片是固定宽度的框，序列两端处要把它收回绘图区内，
  // 否则会溢出卡片外面。
  const CHIP_W = 78;
  const markerX = marker ? x(marker.time) : 0;
  const chipLeft = marker ? Math.min(Math.max(markerX - CHIP_W / 2, 0), Math.max(width - CHIP_W, 0)) : 0;

  const pickerArrow = (
    <Text style={{ fontSize: 11, color: theme.textFaint, marginLeft: 3 }}>{benchmarkPicker?.open ? '▴' : '▾'}</Text>
  );
  const benchmarkLegend =
    benchmarkSeries.length && benchmark ? (
      <Legend color={theme.warning} label={benchmark.name} value={shownBenchmarkChange} trailing={pickerArrow} />
    ) : (
      <Text style={{ fontSize: 12, color: theme.textMuted, marginRight: 12 }}>选基准</Text>
    );

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      {/* RN-web 的每个 View 都是独立层叠上下文（position:relative + z-index:0），
          展开的下拉菜单因此要在两层同时提权：整行提一层，压过后面渲染的图表；
          触发器再提一层，让面板稳稳贴在基准名称正下方。 */}
      <View style={{ marginBottom: 6, zIndex: benchmarkPicker?.open ? 20 : 0 }}>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center' }}>
          <Legend color={theme.primary} label="本基金" value={shownFundChange} />
          {benchmarkPicker ? (
            <View style={{ zIndex: benchmarkPicker.open ? 20 : 0 }}>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="切换比较基准"
                onPress={benchmarkPicker.onToggle}
                style={{ flexDirection: 'row', alignItems: 'center' }}
              >
                {benchmarkLegend}
              </Pressable>
              {benchmarkPicker.open ? (
                <Pressable
                  accessibilityLabel="关闭基准下拉"
                  onPress={benchmarkPicker.onToggle}
                  style={{ position: 'absolute', top: -600, left: -600, right: -600, bottom: -600, zIndex: 10 }}
                />
              ) : null}
              {benchmarkPicker.open ? (
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
                      key={option.value}
                      accessibilityRole="menuitem"
                      hitSlop={{ top: 8, bottom: 8, left: 10, right: 10 }}
                      onPress={() => benchmarkPicker.onPick(option.value)}
                      style={{ paddingHorizontal: 12, paddingVertical: 9 }}
                    >
                      <Text
                        style={{ fontSize: 13, color: option.value === benchmarkPicker.selected ? theme.primary : theme.text }}
                      >
                        {option.label}
                      </Text>
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </View>
          ) : benchmarkSeries.length && benchmark ? (
            benchmarkLegend
          ) : null}
          {costChange !== null ? (
            <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
              <Text style={{ fontSize: 12, color: theme.textFaint }}>成本价 {costNav?.toFixed(4)}</Text>
            </View>
          ) : null}
        </View>
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
              <Circle cx={x(last.time)} cy={y(lastChange)} r={3} fill={trendColor(lastChange)} />
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
              <Text style={{ fontSize: 11, color: theme.text, textAlign: 'center' }}>{formatDate(marker.label)}</Text>
            </View>
          ) : null}
        </View>
      ) : (
        <View style={{ height: HEIGHT }} />
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(points[0].nav_date)}</Text>
        <Text style={{ fontSize: 11, color: marker ? theme.text : theme.textFaint }}>
          {marker ? formatDate(marker.label) : `${formatReturnPoints(min)} ~ ${formatReturnPoints(max)}`}
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
  /** 插在名称与数字之间，比如下拉的箭头。 */
  trailing?: ReactNode;
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12 }}>
      <View style={{ width: 12, height: 2, backgroundColor: color, marginRight: 5 }} />
      <Text style={{ fontSize: 12, color: theme.textMuted }}>{label}</Text>
      {trailing}
      <Text style={{ fontSize: 12, marginLeft: 4, color: trendColor(value) }}>{formatReturnPoints(value)}</Text>
    </View>
  );
}
