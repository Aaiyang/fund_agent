/**
 * 迷你分时线：一张卡片那么大，画当日盘中走势 + 昨收参考虚线 + 线下渐变。
 *
 * 宽度交给 `width="100%"` 和 viewBox 缩放，不去量容器：靠 `onLayout` 拿宽度的
 * 写法在浏览器面板隐藏时压根不回调（量出来是 0），而这种小图本来就没有交互。
 * 昨收也参与纵轴取值范围，否则价格一路在昨收下方走时虚线会被挤出画框。
 */

import { type StyleProp, type ViewStyle, View } from 'react-native';
import Svg, { Defs, Line, LinearGradient, Polygon, Polyline, Stop } from 'react-native-svg';

import { theme } from '@/constants/theme';
import { trendColor } from '@/utils/format';

const VIEW_W = 100;
const PAD = 3;

export function MiniTrend({
  prices,
  prevClose,
  gradientKey,
  height = 46,
  style,
}: {
  /** 当日盘中每分钟价格，按时间顺序。 */
  prices: number[];
  /** 昨收：决定涨跌配色，也用来画那条基准虚线。 */
  prevClose?: number | null;
  /**
   * 渐变的 DOM id 后缀，**同一屏内必须唯一**：web 上 `url(#id)` 是按整个文档
   * 解析的，两张卡撞了 id 就会共用另一张卡的涨跌色。
   */
  gradientKey: string;
  height?: number;
  style?: StyleProp<ViewStyle>;
}) {
  const gradientId = `minitrend-${gradientKey}`;
  const series = prices.filter((value) => Number.isFinite(value));
  if (series.length < 2) {
    // 不足两个点谈不上走势，留白比画一根横线诚实。
    return <View style={[{ height }, style]} />;
  }

  const last = series[series.length - 1];
  // 与数字读数同一口径走 trendColor：收在昨收上持平用灰，缺昨收时才默认红。
  const color = prevClose == null ? theme.up : trendColor(last - prevClose);

  const domain = prevClose == null ? series : [...series, prevClose];
  const min = Math.min(...domain);
  const max = Math.max(...domain);
  // 全程一条直线时也给个跨度，免得除零把点算成 NaN。
  const span = max - min || 1;
  const yAt = (value: number) => height - PAD - ((value - min) / span) * (height - PAD * 2);
  const step = VIEW_W / (series.length - 1);
  const line = series.map((value, index) => `${(index * step).toFixed(2)},${yAt(value).toFixed(2)}`).join(' ');
  const area = `0,${height} ${line} ${VIEW_W},${height}`;

  return (
    <View style={[{ height }, style]}>
      <Svg width="100%" height={height} viewBox={`0 0 ${VIEW_W} ${height}`} preserveAspectRatio="none">
        <Defs>
          <LinearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <Stop offset="0%" stopColor={color} stopOpacity={0.2} />
            <Stop offset="100%" stopColor={color} stopOpacity={0} />
          </LinearGradient>
        </Defs>
        <Polygon points={area} fill={`url(#${gradientId})`} />
        {prevClose != null && prevClose >= min && prevClose <= max ? (
          <Line
            x1={0}
            y1={yAt(prevClose)}
            x2={VIEW_W}
            y2={yAt(prevClose)}
            stroke={theme.textFaint}
            strokeWidth={0.8}
            strokeDasharray="3,3"
          />
        ) : null}
        <Polyline points={line} fill="none" stroke={color} strokeWidth={1.4} strokeLinejoin="round" />
      </Svg>
    </View>
  );
}
