/**
 * 板块热力图：面积 = 选定指标，颜色深浅 = 涨跌幅（涨红跌绿）.
 *
 * 布局是 `@/utils/treemap` 里的 squarified treemap（纯几何，可单独核对）。
 * 宽度由调用方按 `Dimensions` 算好传进来，不在这里量容器：靠 `onLayout` 的写法
 * 在浏览器面板隐藏时拿到的宽度是 0，整张图会直接消失。
 */

import { Text, View } from 'react-native';

import { theme } from '@/constants/theme';
import { formatReturnPoints, formatYi } from '@/utils/format';
import { squarify } from '@/utils/treemap';
import type { SectorBoardItem } from '@/hooks/useSectors';

const GAP = 2;

/**
 * 涨跌幅分档着色：绝对值越大越深，0 与缺失走中性灰，不猜方向。
 * 这是热力图专属的独立色阶（深浅分级），故不并入 trendColor 的三档涨跌色；
 * 但灰档与 theme.textFaint 同值，直接引用主题色，不留手写十六进制。
 */
const UP_SHADES = ['#F79A9C', '#F26B6E', '#E04A4F', '#CC2A31', '#B01219'];
const DOWN_SHADES = ['#8FCBAF', '#4FB98A', '#1E9E62', '#12855B', '#0B6B49'];

export function heatColor(changePct: number | null | undefined): string {
  if (changePct === null || changePct === undefined || changePct === 0) return theme.textFaint;
  const abs = Math.abs(changePct);
  const step = abs >= 5 ? 4 : abs >= 3 ? 3 : abs >= 1.5 ? 2 : abs >= 0.5 ? 1 : 0;
  return changePct > 0 ? UP_SHADES[step] : DOWN_SHADES[step];
}

/**
 * 渲染板块热力图。
 *
 * `sort` 决定面积用哪个指标；该指标缺失的板块画不出来（0 面积没有意义），
 * 数量由调用方在图下说明，不偷偷补成 0。
 */
export function SectorTreemap({
  sectors,
  sort,
  width,
  height = 300,
}: {
  sectors: SectorBoardItem[];
  sort: 'change_pct' | 'amount';
  width: number;
  height?: number;
}) {
  const measurable = sectors
    .map((item) => ({ item, value: sort === 'amount' ? item.amount : item.change_pct }))
    .filter((entry): entry is { item: SectorBoardItem; value: number } => entry.value !== null && entry.value > 0)
    .sort((left, right) => right.value - left.value);

  const cells = squarify(measurable, width, height);

  return (
    <View style={{ width, height }}>
      {cells.map((cell) => {
        const label = cell.item.name;
        // `formatYi` 要求传进来的已经是「亿」，上游成交额是元，先除再格式化。
        const valueText = sort === 'amount' ? formatYi((cell.item.amount ?? 0) / 1e8) : formatReturnPoints(cell.item.change_pct);
        const secondText = sort === 'amount' ? formatReturnPoints(cell.item.change_pct) : null;
        const innerWidth = cell.w - GAP * 2;
        const innerHeight = cell.h - GAP * 2;
        // 方块装不下就不写字，宁可留白也不截断成「传媒娱…」。
        // 字色固定白色系：热力色阶最深只到 #B01219/#0B6B49，白字始终可读，不随涨跌读数色规则走。
        const showValue = innerWidth >= 56 && innerHeight >= 44;
        const showName = innerWidth >= 34 && innerHeight >= 20;
        return (
          <View
            key={cell.item.code}
            style={{
              position: 'absolute',
              left: cell.x,
              top: cell.y,
              width: Math.max(cell.w - GAP, 0),
              height: Math.max(cell.h - GAP, 0),
              backgroundColor: heatColor(cell.item.change_pct),
              borderRadius: 4,
              padding: 6,
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {showName ? (
              <Text style={{ fontSize: innerWidth >= 96 ? 15 : 12, color: '#FFFFFF', fontWeight: '600' }} numberOfLines={2}>
                {label}
              </Text>
            ) : null}
            {showValue ? (
              <Text style={{ fontSize: 12, color: 'rgba(255,255,255,0.92)', marginTop: 2 }} numberOfLines={1}>
                {valueText}
              </Text>
            ) : null}
            {showValue && secondText ? (
              <Text style={{ fontSize: 12, color: 'rgba(255,255,255,0.92)' }} numberOfLines={1}>
                {secondText}
              </Text>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}
