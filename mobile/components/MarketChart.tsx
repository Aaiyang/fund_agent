/**
 * 单只上市品种的价格图：K 线加成交量副图，或当日分时线。
 *
 * 两种模式共用一套布局：每个点占一个等宽槽位（交易日和分钟本来就是均匀
 * 离散的，若按真实时间画轴，分时图中间会被午休挖出一个空洞），上半是价格
 * 区、下半是成交量区，十字光标跟随按压与拖动。
 *
 * 只用 react-native-svg，与 NavChart 保持同一做法：那边本来就已经自绘坐标轴，
 * 而第三方 K 线库建立在 web 上跑不起来的手势原语之上。
 */

import { useRef, useState } from 'react';
import { type GestureResponderEvent, ScrollView, Text, View } from 'react-native';
import Svg, { Line, Polyline, Rect } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { useDragScroll } from '@/hooks/useDragScroll';
import { formatCompact, formatDate } from '@/utils/format';

export type ChartBar = {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume?: number | null;
};

export type ChartMinute = {
  time: string;
  price: number;
  volume?: number | null;
  average_price?: number | null;
  /** 只有五日序列会填这个字段，其数据点横跨多个场次。 */
  trade_date?: string | null;
};

const PRICE_HEIGHT = 190;
const VOLUME_HEIGHT = 44;
const GAP = 8;
const PADDING = 6;
const CHIP_WIDTH = 116;
// 一根 K 线对应一个交易日，手机宽的卡片大约摆得下三个月。
const CANDLE_SLOT_W = 7;
// 五日分时大约 1200 分钟，一分钟一根成交量柱会糊成一片，所以
// 把连续分钟加总起来，柱数最多到这里这个上限。
const MAX_VOLUME_BARS = 300;

type Slot = {
  label: string;
  price: number;
  /** 相对昨收的涨跌幅，供十字光标的读数用。 */
  changePct: number | null;
  volume: number | null;
  up: boolean;
  open?: number;
  high?: number;
  low?: number;
  average?: number | null;
  /** 五日序列里，新场次开始的第一分钟。 */
  newDay?: boolean;
};

function candleSlots(bars: ChartBar[]): Slot[] {
  return bars.map((bar, index) => ({
    label: bar.trade_date,
    price: bar.close,
    changePct:
      index > 0 && bars[index - 1].close ? ((bar.close - bars[index - 1].close) / bars[index - 1].close) * 100 : null,
    volume: bar.volume ?? null,
    up: bar.close >= bar.open,
    open: bar.open,
    high: bar.high,
    low: bar.low,
  }));
}

function minuteSlots(points: ChartMinute[], prevClose: number | null): Slot[] {
  return points.map((point, index) => ({
    // 单个场次看钟点就够；五个场次必须连日期一起显示。
    label: point.trade_date ? `${point.trade_date.slice(5)} ${point.time}` : point.time,
    price: point.price,
    changePct: prevClose ? ((point.price - prevClose) / prevClose) * 100 : null,
    volume: point.volume ?? null,
    // 一分钟涨没涨，看它是否不低于前一分钟。
    up: index === 0 ? point.price >= (prevClose ?? point.price) : point.price >= points[index - 1].price,
    average: point.average_price ?? null,
    newDay: index === 0 || Boolean(point.trade_date && point.trade_date !== points[index - 1].trade_date),
  }));
}

export function MarketChart({
  bars,
  minutes,
  prevClose,
  volumeUnit,
}: {
  /** K 线模式传入；与 `minutes` 互斥。 */
  bars?: ChartBar[];
  minutes?: ChartMinute[];
  /** 分时坐标轴的参照位（昨收）。 */
  prevClose?: number | null;
  /** 来自行情的 手 或 股：量柱只画相对高度，读数文字才需要单位。 */
  volumeUnit?: string | null;
}) {
  const [width, setWidth] = useState(0);
  const isCandle = Boolean(bars);
  const scrollRef = useRef<ScrollView>(null);
  const anchored = useRef<string | null>(null);
  // 卡片量出宽度之后滚动容器才真实存在，所以 `width > 0` 同时充当
  // （重新）绑定鼠标拖动平移的信号。
  useDragScroll(scrollRef, isCandle && width > 0);
  // 按下的点记住自己来自哪条序列：切换周期或模式后，旧光标直接作废，
  // 而不是指着另一天的数据。
  const [pinned, setPinned] = useState<{ series: string; index: number } | null>(null);

  const slots = bars ? candleSlots(bars) : minutes ? minuteSlots(minutes, prevClose ?? null) : [];
  const seriesKey = bars
    ? `bars:${bars.length}:${bars[0]?.trade_date ?? ''}:${bars[bars.length - 1]?.trade_date ?? ''}`
    : `minutes:${slots.length}:${slots[0]?.label ?? ''}`;

  if (slots.length < 2) {
    return (
      <View style={{ height: PRICE_HEIGHT + VOLUME_HEIGHT + GAP, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: theme.textFaint, fontSize: 13 }}>{isCandle ? '暂无K线数据' : '当前没有分时数据（未开盘）'}</Text>
      </View>
    );
  }

  const prices = slots.flatMap((slot) => [slot.high ?? slot.price, slot.low ?? slot.price]);
  const rawLow = Math.min(...prices);
  const rawHigh = Math.max(...prices);
  // 分时轴以昨收为中心上下对称：两半分别对应“涨了多少 / 跌了多少”，
  // 一眼就能读出来。
  const reference = !isCandle && prevClose ? prevClose : null;
  const deviation = reference ? Math.max(Math.abs(rawHigh - reference), Math.abs(rawLow - reference)) : 0;
  const high = reference ? reference + deviation : rawHigh;
  const low = reference ? reference - deviation : rawLow;
  const span = high - low || Math.abs(high) || 1;

  // K 线用固定槽宽，窗口放不下就整体横向滚动，36 根的月K也能铺满
  // 卡片而不是悬在半空；
  // 分时线则恒把一个场次压进可视宽度内。
  const slotWidth = isCandle ? Math.max(CANDLE_SLOT_W, width / slots.length) : width / slots.length;
  const plotWidth = slotWidth * slots.length;
  const x = (index: number) => index * slotWidth + slotWidth / 2;
  const y = (price: number) => PADDING + ((high - price) / span) * (PRICE_HEIGHT - PADDING * 2);

  // 一个点一根柱会把五日序列糊成一整片，所以把连续的点加总成
  // 至多 MAX_VOLUME_BARS 个分组。
  const bucket = Math.max(Math.ceil(slots.length / MAX_VOLUME_BARS), 1);
  const groups: { start: number; volume: number; up: boolean }[] = [];
  for (let index = 0; index < slots.length; index += bucket) {
    const slice = slots.slice(index, index + bucket);
    groups.push({
      start: index,
      volume: slice.reduce((sum, slot) => sum + (slot.volume ?? 0), 0),
      up: slice[slice.length - 1].up,
    });
  }
  const maxVolume = Math.max(...groups.map((group) => group.volume), 0);
  const barWidth = Math.max(Math.min(slotWidth * bucket * 0.62, 14), 1);

  const dayStarts = slots.map((slot, index) => (slot.newDay ? index : -1)).filter((index) => index >= 0);
  const multiDay = dayStarts.length > 1;

  const bodyWidth = Math.max(Math.min(slotWidth * 0.62, 14), 1);
  const marker = pinned && pinned.series === seriesKey ? pinned.index : null;
  const shown = marker === null ? null : slots[marker];
  // 成交量区的数字跟着十字光标走，没按的时候退回最新一根；没有它，
  // 量柱只有形状没有量。它读的是光标落在的那个*分组*的总量，
  // 所以数字永远和柱子的高度对得上。
  const readoutIndex = marker ?? slots.length - 1;
  const readout =
    groups.find((group) => readoutIndex >= group.start && readoutIndex < group.start + bucket) ?? groups[groups.length - 1];

  const locate = (event: GestureResponderEvent) => {
    const locationX = event.nativeEvent.locationX;
    if (plotWidth <= 0 || locationX === undefined || locationX === null) return;
    const index = Math.min(Math.max(Math.floor(locationX / slotWidth), 0), slots.length - 1);
    setPinned({ series: seriesKey, index });
  };

  const anchorLatest = () => {
    // 行情图打开时停在最新一根，更早的数据往左拖就有。
    if (anchored.current !== seriesKey) {
      anchored.current = seriesKey;
      scrollRef.current?.scrollToEnd({ animated: false });
    }
  };

  const markerX = marker === null ? 0 : x(marker);
  const chipLeft =
    marker === null ? 0 : Math.min(Math.max(markerX - CHIP_WIDTH / 2, 0), Math.max(plotWidth - CHIP_WIDTH, 0));
  const linePath = (value: (slot: Slot) => number | null | undefined) =>
    slots
      .map((slot, index) => {
        const point = value(slot);
        return point === null || point === undefined ? null : `${x(index).toFixed(2)},${y(point).toFixed(2)}`;
      })
      .filter(Boolean)
      .join(' ');
  const pricePath = linePath((slot) => slot.price);
  const averagePath = linePath((slot) => slot.average);

  // 读数贴片画在绘图区内部，这样它和自己标注的那根柱子一起滚动。
  const plot = (
    <View
      onLayout={anchorLatest}
      accessibilityLabel="点选查看该日行情，左右拖动看更早的"
      onStartShouldSetResponder={() => true}
      onMoveShouldSetResponder={() => true}
      onResponderTerminationRequest={() => false}
      onResponderGrant={locate}
      onResponderMove={locate}
    >
          <Svg width={plotWidth} height={PRICE_HEIGHT + GAP + VOLUME_HEIGHT}>
            {reference === null ? null : (
              <Line x1={0} y1={y(reference)} x2={plotWidth} y2={y(reference)} stroke={theme.textFaint} strokeWidth={1} strokeDasharray="5,4" />
            )}

            {isCandle
              ? slots.map((slot, index) => {
                  const color = slot.up ? theme.up : theme.down;
                  const open = slot.open ?? slot.price;
                  const top = y(Math.max(open, slot.price));
                  const bottom = y(Math.min(open, slot.price));
                  return [
                    <Line
                      key={`wick-${index}`}
                      x1={x(index)}
                      y1={y(slot.high ?? slot.price)}
                      x2={x(index)}
                      y2={y(slot.low ?? slot.price)}
                      stroke={color}
                      strokeWidth={1}
                    />,
                    <Rect
                      key={`body-${index}`}
                      x={x(index) - bodyWidth / 2}
                      y={top}
                      width={bodyWidth}
                      height={Math.max(bottom - top, 1)}
                      fill={color}
                    />,
                  ];
                })
              : null}

            {isCandle ? null : (
              <Polyline points={pricePath} fill="none" stroke={theme.primary} strokeWidth={1.6} />
            )}
            {isCandle || !averagePath ? null : (
              <Polyline points={averagePath} fill="none" stroke={theme.warning} strokeWidth={1.2} />
            )}

            {groups.map((group) => {
              const height = maxVolume ? (group.volume / maxVolume) * VOLUME_HEIGHT : 0;
              if (!height) return null;
              return (
                <Rect
                  key={`volume-${group.start}`}
                  x={x(group.start) - barWidth / 2}
                  y={PRICE_HEIGHT + GAP + VOLUME_HEIGHT - height}
                  width={barWidth}
                  height={height}
                  fill={group.up ? theme.up : theme.down}
                  opacity={0.55}
                />
              );
            })}

            {/* 场次分界线，五日线才能按天一段段地读。 */}
            {multiDay
              ? dayStarts
                  .filter((index) => index > 0)
                  .map((index) => (
                    <Line
                      key={`day-${index}`}
                      x1={x(index) - slotWidth / 2}
                      y1={0}
                      x2={x(index) - slotWidth / 2}
                      y2={PRICE_HEIGHT + GAP + VOLUME_HEIGHT}
                      stroke={theme.border}
                      strokeWidth={1}
                    />
                  ))
              : null}

            {marker === null ? null : (
              <Line
                x1={markerX}
                y1={0}
                x2={markerX}
                y2={PRICE_HEIGHT + GAP + VOLUME_HEIGHT}
                stroke={theme.textMuted}
                strokeWidth={1}
                strokeDasharray="3,3"
              />
            )}
            {shown ? (
              <Line
                x1={0}
                y1={y(shown.price)}
                x2={plotWidth}
                y2={y(shown.price)}
                stroke={theme.textMuted}
                strokeWidth={1}
                strokeDasharray="3,3"
              />
            ) : null}
          </Svg>

          {shown ? (
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                top: 0,
                left: chipLeft,
                width: CHIP_WIDTH,
                borderRadius: 4,
                backgroundColor: theme.surface,
                borderWidth: 1,
                borderColor: theme.border,
                paddingVertical: 3,
                paddingHorizontal: 4,
              }}
            >
              <Text style={{ fontSize: 10, color: theme.text, textAlign: 'center' }}>
                {isCandle ? formatDate(shown.label) : shown.label}
              </Text>
              <Text style={{ fontSize: 11, fontWeight: '600', color: theme.text, textAlign: 'center' }}>
                {shown.price.toFixed(2)}
                {isCandle && shown.open !== undefined ? ` 开${shown.open.toFixed(2)} 高${(shown.high ?? 0).toFixed(2)}` : ''}
              </Text>
              {shown.changePct === null ? null : (
                <Text
                  style={{
                    fontSize: 10,
                    textAlign: 'center',
                    color: shown.changePct >= 0 ? theme.up : theme.down,
                  }}
                >
                  {`${shown.changePct > 0 ? '+' : ''}${shown.changePct.toFixed(2)}%`}
                </Text>
              )}
            </View>
          ) : null}
    </View>
  );

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      {width > 0 ? (
        <>
          {isCandle ? (
            <ScrollView ref={scrollRef} horizontal showsHorizontalScrollIndicator={false}>
              {plot}
            </ScrollView>
          ) : (
            plot
          )}
          {/* 钉在视口上而不是内容上：K 线在它底下横向滚过。 */}
          <View
            pointerEvents="none"
            style={{
              position: 'absolute',
              top: PRICE_HEIGHT + GAP - 2,
              left: 0,
              backgroundColor: theme.surface,
              paddingHorizontal: 3,
              borderRadius: 3,
            }}
          >
            <Text style={{ fontSize: 10, color: readout.up ? theme.up : theme.down }}>
              {`量 ${formatCompact(readout.volume)}${volumeUnit ?? ''}`}
            </Text>
          </View>
        </>
      ) : (
        <View style={{ height: PRICE_HEIGHT + VOLUME_HEIGHT + GAP }} />
      )}

      {multiDay ? (
        <View style={{ position: 'relative', height: 14, marginTop: 4 }}>
          {dayStarts.map((index) => (
            <Text
              key={`axis-${index}`}
              style={{ position: 'absolute', left: Math.min(x(index), plotWidth - 34), fontSize: 11, color: theme.textFaint }}
            >
              {slots[index].label.slice(0, 5)}
            </Text>
          ))}
        </View>
      ) : (
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
          <Text style={{ fontSize: 11, color: theme.textFaint }}>
            {isCandle ? formatDate(slots[0].label) : slots[0].label}
          </Text>
          <Text style={{ fontSize: 11, color: theme.textFaint }}>
            {reference
              ? `${(((high - reference) / reference) * 100).toFixed(2)}% ~ ${(((low - reference) / reference) * 100).toFixed(2)}%`
              : `${low.toFixed(2)} ~ ${high.toFixed(2)}`}
          </Text>
          <Text style={{ fontSize: 11, color: theme.textFaint }}>
            {isCandle ? formatDate(slots[slots.length - 1].label) : slots[slots.length - 1].label}
          </Text>
        </View>
      )}
    </View>
  );
}
