/**
 * Price chart for one listed instrument: candlesticks with a volume pane, or
 * the current session's minute line.
 *
 * Both modes share one layout: an evenly-spaced slot per point (trading days
 * and minutes are both uniform, and a time axis would leave the lunch break as
 * a hole in the middle of the 分时), a price pane above a volume pane, and a
 * crosshair that follows a press or a drag.
 *
 * react-native-svg only, matching NavChart: the app already draws its own axes
 * there, and the third-party candlestick libraries are built on gesture
 * primitives that do not run on web.
 */

import { useState } from 'react';
import { type GestureResponderEvent, Text, View } from 'react-native';
import Svg, { Line, Polyline, Rect } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate } from '@/utils/format';

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
};

const PRICE_HEIGHT = 190;
const VOLUME_HEIGHT = 44;
const GAP = 8;
const PADDING = 6;
const CHIP_WIDTH = 116;

type Slot = {
  label: string;
  price: number;
  /** Percent against the previous close, for the crosshair readout. */
  changePct: number | null;
  volume: number | null;
  up: boolean;
  open?: number;
  high?: number;
  low?: number;
  average?: number | null;
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
    label: point.time,
    price: point.price,
    changePct: prevClose ? ((point.price - prevClose) / prevClose) * 100 : null,
    volume: point.volume ?? null,
    // A minute counts as up when it traded at or above the minute before it.
    up: index === 0 ? point.price >= (prevClose ?? point.price) : point.price >= points[index - 1].price,
    average: point.average_price ?? null,
  }));
}

export function MarketChart({
  bars,
  minutes,
  prevClose,
}: {
  /** Set for the K-line modes; mutually exclusive with `minutes`. */
  bars?: ChartBar[];
  minutes?: ChartMinute[];
  /** Session reference for the 分时 axis. */
  prevClose?: number | null;
}) {
  const [width, setWidth] = useState(0);
  // The pressed point remembers which series it came from, so switching range
  // or mode drops the stale crosshair instead of pointing at another day.
  const [pinned, setPinned] = useState<{ series: string; index: number } | null>(null);

  const slots = bars ? candleSlots(bars) : minutes ? minuteSlots(minutes, prevClose ?? null) : [];
  const seriesKey = bars
    ? `bars:${bars.length}:${bars[0]?.trade_date ?? ''}:${bars[bars.length - 1]?.trade_date ?? ''}`
    : `minutes:${slots.length}:${slots[0]?.label ?? ''}`;
  const isCandle = Boolean(bars);

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
  // A 分时 axis is symmetric around the previous close: that is how the two
  // halves read as "涨了多少 / 跌了多少" at a glance.
  const reference = !isCandle && prevClose ? prevClose : null;
  const deviation = reference ? Math.max(Math.abs(rawHigh - reference), Math.abs(rawLow - reference)) : 0;
  const high = reference ? reference + deviation : rawHigh;
  const low = reference ? reference - deviation : rawLow;
  const span = high - low || Math.abs(high) || 1;

  const slotWidth = width / slots.length;
  const x = (index: number) => index * slotWidth + slotWidth / 2;
  const y = (price: number) => PADDING + ((high - price) / span) * (PRICE_HEIGHT - PADDING * 2);

  const maxVolume = Math.max(...slots.map((slot) => slot.volume ?? 0), 0);
  const volumeHeight = (volume: number | null) =>
    volume && maxVolume ? (volume / maxVolume) * VOLUME_HEIGHT : 0;

  const bodyWidth = Math.max(Math.min(slotWidth * 0.62, 14), 1);
  const marker = pinned && pinned.series === seriesKey ? pinned.index : null;
  const shown = marker === null ? null : slots[marker];

  const locate = (event: GestureResponderEvent) => {
    const locationX = event.nativeEvent.locationX;
    if (width <= 0 || locationX === undefined || locationX === null) return;
    const index = Math.min(Math.max(Math.floor(locationX / slotWidth), 0), slots.length - 1);
    setPinned({ series: seriesKey, index });
  };

  const markerX = marker === null ? 0 : x(marker);
  const chipLeft = marker === null ? 0 : Math.min(Math.max(markerX - CHIP_WIDTH / 2, 0), Math.max(width - CHIP_WIDTH, 0));
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

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      {width > 0 ? (
        <View
          accessibilityLabel="点选或左右拖动查看该日行情"
          onStartShouldSetResponder={() => true}
          onMoveShouldSetResponder={() => true}
          onResponderTerminationRequest={() => false}
          onResponderGrant={locate}
          onResponderMove={locate}
        >
          <Svg width={width} height={PRICE_HEIGHT + GAP + VOLUME_HEIGHT}>
            {reference === null ? null : (
              <Line x1={0} y1={y(reference)} x2={width} y2={y(reference)} stroke={theme.textFaint} strokeWidth={1} strokeDasharray="5,4" />
            )}
            {reference === null ? (
              <Line x1={0} y1={y((high + low) / 2)} x2={width} y2={y((high + low) / 2)} stroke={theme.border} strokeWidth={1} />
            ) : null}

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

            {slots.map((slot, index) => {
              const height = volumeHeight(slot.volume);
              if (!height) return null;
              return (
                <Rect
                  key={`volume-${slot.label}-${index}`}
                  x={x(index) - bodyWidth / 2}
                  y={PRICE_HEIGHT + GAP + VOLUME_HEIGHT - height}
                  width={bodyWidth}
                  height={height}
                  fill={slot.up ? theme.up : theme.down}
                  opacity={0.55}
                />
              );
            })}

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
                x2={width}
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
      ) : (
        <View style={{ height: PRICE_HEIGHT + VOLUME_HEIGHT + GAP }} />
      )}

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
    </View>
  );
}
