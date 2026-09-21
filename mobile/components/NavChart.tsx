/**
 * NAV line chart. react-native-svg only — no charting dependency: the series
 * is a few hundred points at most and the shape is a single polyline.
 */

import { useState } from 'react';
import { Text, View } from 'react-native';
import Svg, { Circle, Line, Polyline } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { formatDate, formatNumber } from '@/utils/format';

type Point = { nav_date: string; unit_nav?: number | null };

const HEIGHT = 180;
const PADDING = 6;

export function NavChart({ points }: { points: Point[] }) {
  const [width, setWidth] = useState(0);
  const series = points.filter((point): point is { nav_date: string; unit_nav: number } => point.unit_nav !== null);

  if (series.length < 2) {
    return (
      <View style={{ height: HEIGHT, alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: theme.textFaint, fontSize: 13 }}>净值数据不足，暂无法绘制走势</Text>
      </View>
    );
  }

  const values = series.map((point) => point.unit_nav);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const x = (index: number) => (index / (series.length - 1)) * width;
  const y = (value: number) => HEIGHT - PADDING - ((value - min) / span) * (HEIGHT - PADDING * 2);
  const coordinates = series.map((point, index) => `${x(index).toFixed(2)},${y(point.unit_nav).toFixed(2)}`).join(' ');
  const last = series[series.length - 1];

  return (
    <View onLayout={(event) => setWidth(event.nativeEvent.layout.width)}>
      {width > 0 ? (
        <Svg width={width} height={HEIGHT}>
          <Line x1={0} y1={y(max)} x2={width} y2={y(max)} stroke={theme.border} strokeWidth={1} />
          <Line x1={0} y1={y(min)} x2={width} y2={y(min)} stroke={theme.border} strokeWidth={1} />
          <Polyline points={coordinates} fill="none" stroke={theme.primary} strokeWidth={2} />
          <Circle
            cx={x(series.length - 1)}
            cy={y(last.unit_nav)}
            r={3}
            fill={last.unit_nav >= values[0] ? theme.up : theme.down}
          />
        </Svg>
      ) : (
        <View style={{ height: HEIGHT }} />
      )}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 4 }}>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(series[0].nav_date)}</Text>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>
          {formatNumber(min)} ~ {formatNumber(max)}
        </Text>
        <Text style={{ fontSize: 11, color: theme.textFaint }}>{formatDate(last.nav_date)}</Text>
      </View>
    </View>
  );
}
