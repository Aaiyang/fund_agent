/**
 * 多基金归一收益图：所有曲线从同一共同窗口的首个共同净值定基为 0%。
 *
 * 只画累计变化，不画原始净值；基金净值基数不同，原始净值曲线没有可比性。
 * 交互与 NavChart 一致：点按/拖动看同一天的日期与每条曲线读数。
 */

import { useState } from 'react';
import { type GestureResponderEvent, Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate, formatReturnPoints, trendColor } from '@/utils/format';

export type ComparisonSeries = {
  fund_code: string;
  fund_name?: string | null;
  points: { nav_date: string; change_ratio: number }[];
};

export const COMPARISON_COLORS = ['#3F6E8C', '#806333', '#A35D3B'] as const;

const HEIGHT = 180;
const PADDING = 8;
const CHIP_W = 78;

export function ComparisonChart({
  funds,
  mode = 'return',
  minFunds = 2,
}: {
  funds: ComparisonSeries[];
  mode?: 'return' | 'drawdown';
  /** 回撤模式下允许只画已算出回撤的对象，因此可降到 1 条. */
  minFunds?: number;
}) {
  const [width, setWidth] = useState(0);
  const [active, setActive] = useState<number | null>(null);

  const usable = funds.filter((fund) => (fund.points?.length ?? 0) >= 2);
  const count = usable[0]?.points.length ?? 0;
  const aligned = usable.length >= minFunds && usable.every((fund) => fund.points.length === count);
  if (!aligned) {
    return (
      <View style={{ height: HEIGHT, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ fontSize: 13, color: theme.textMuted }}>对比数据没有对齐到同一组共同日期</Text>
      </View>
    );
  }

  const dates = usable[0].points.map((point) => point.nav_date);
  const series = usable.map((fund, index) => {
    const changes = fund.points.map((point) => point.change_ratio * 100);
    let peak = 1;
    const values = mode === 'return'
      ? changes
      : fund.points.map((point) => {
        const indexValue = 1 + point.change_ratio;
        peak = Math.max(peak, indexValue);
        return (indexValue / peak - 1) * 100;
      });
    return {
      code: fund.fund_code,
      name: fund.fund_name || fund.fund_code,
      color: COMPARISON_COLORS[index % COMPARISON_COLORS.length],
      values,
    };
  });
  const all = series.flatMap((item) => item.values);
  const min = Math.min(...all, 0);
  const max = Math.max(...all, 0);
  const span = max - min || 1;
  const activeIndex = active === null ? null : Math.min(active, count - 1);
  const x = (index: number) => (index / (count - 1 || 1)) * width;
  const y = (value: number) => HEIGHT - PADDING - ((value - min) / span) * (HEIGHT - PADDING * 2);

  function locate(event: GestureResponderEvent) {
    const locationX = event.nativeEvent.locationX;
    if (width <= 0 || locationX === undefined || locationX === null) return;
    const ratio = Math.min(Math.max(locationX / width, 0), 1);
    setActive(Math.round(ratio * (count - 1)));
  }

  const markerX = activeIndex === null ? 0 : x(activeIndex);
  const chipLeft = Math.min(Math.max(markerX - CHIP_W / 2, 0), Math.max(width - CHIP_W, 0));

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 6 }}>
        {series.map((item) => {
          const value = activeIndex === null ? item.values[count - 1] : item.values[activeIndex];
          return (
            <View
              key={item.code}
              style={{ flexDirection: 'row', alignItems: 'center', marginRight: 12, marginBottom: 4, maxWidth: '100%' }}
            >
              <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: item.color }} />
              <Text numberOfLines={1} style={{ marginLeft: 5, maxWidth: 128, fontSize: 12, color: theme.textMuted }}>
                {item.name}
              </Text>
              <Text style={{ marginLeft: 4, fontSize: 12, fontWeight: '600', color: trendColor(value) }}>
                {formatReturnPoints(value)}
              </Text>
            </View>
          );
        })}
      </View>

      {width > 0 ? (
        <View
          accessibilityLabel={mode === 'return' ? '点选或左右拖动查看同一天的基金累计收益' : '点选或左右拖动查看同一天的基金回撤'}
          onStartShouldSetResponder={() => true}
          onMoveShouldSetResponder={() => true}
          onResponderTerminationRequest={() => false}
          onResponderGrant={locate}
          onResponderMove={locate}
        >
          <Svg width={width} height={HEIGHT}>
            <Line x1={0} y1={y(0)} x2={width} y2={y(0)} stroke={theme.border} strokeWidth={1} />
            {series.map((item) => (
              <Polyline
                key={item.code}
                points={item.values.map((value, index) => `${x(index).toFixed(2)},${y(value).toFixed(2)}`).join(' ')}
                fill="none"
                stroke={item.color}
                strokeWidth={2}
              />
            ))}
            {series.map((item) => (
              <Circle key={`${item.code}-end`} cx={x(count - 1)} cy={y(item.values[count - 1])} r={2.6} fill={item.color} />
            ))}
            {activeIndex !== null ? (
              <>
                <Line
                  x1={markerX}
                  y1={0}
                  x2={markerX}
                  y2={HEIGHT}
                  stroke={theme.textMuted}
                  strokeWidth={1}
                  strokeDasharray="3,3"
                />
                {series.map((item) => (
                  <Circle key={`${item.code}-active`} cx={markerX} cy={y(item.values[activeIndex])} r={3.5} fill={item.color} />
                ))}
              </>
            ) : null}
          </Svg>
          {activeIndex !== null ? (
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
              <Text style={{ fontSize: 11, color: theme.text, textAlign: 'center' }}>{formatDate(dates[activeIndex])}</Text>
            </View>
          ) : null}
        </View>
      ) : (
        <View style={{ height: HEIGHT }} />
      )}

      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(dates[0])}</Text>
        <Text style={{ fontSize: 11, color: activeIndex === null ? theme.textFaint : theme.text }}>
          {activeIndex === null ? '拖动查看' : formatDate(dates[activeIndex])}
        </Text>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(dates[count - 1])}</Text>
      </View>
    </View>
  );
}
