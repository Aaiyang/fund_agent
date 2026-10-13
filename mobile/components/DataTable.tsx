/**
 * 数据表格：名称列固定不动，指标列作为一整块横向滚动；自选和持仓共用，
 * 两边看起来口径一致。
 *
 * 若每行各带一个横向滚动条，各行会漂到各自的偏移、彼此错位，所以右半侧
 * 做成单个滚动容器，表头用一个 `scrollEnabled={false}` 的副本跟着镜像滚动。
 */

import { type Href, Link } from 'expo-router';
import { type StyleProp, type ViewStyle, type NativeScrollEvent, type NativeSyntheticEvent, Pressable, ScrollView, Text, View } from 'react-native';
import { useEffect, useRef, useState } from 'react';

import { theme } from '@/constants/theme';

const NAME_W = 132;
const ACTION_W = 56;
const ROW_H = 58;
/**
 * 每格的内容从行顶往下 CELL_TOP 起排，整行才有一条共同的首行基线。
 * 带副文本的格子最高（13px 值 + 2 + 11px 副文本 = 34），按它居中：(58-34)/2。
 * 之前是每格各自居中，单行格子和两行格子差了 8px，一行数字看着是锯齿。
 */
const CELL_TOP = 12;

const nameCellStyle = {
  width: NAME_W,
  height: ROW_H,
  paddingTop: CELL_TOP,
  paddingEnd: 8,
  borderBottomWidth: 1,
  borderColor: theme.border,
} as const;

export type DataCell = {
  text: string;
  color?: string;
  sub?: string;
  subColor?: string;
  /** 数字列右对齐才比得出来大小；非数字的占位（新增/未接入）用 center。 */
  align?: 'left' | 'center' | 'right';
};

export type DataColumn<T> = {
  key: string;
  title: string;
  width: number;
  cell: (item: T) => DataCell;
  /** 格式化单元格背后的原始值；不给它就等于该列不可排序。 */
  sortValue?: (item: T) => number | string | null | undefined;
};

function sortArrow(active: 'asc' | 'desc' | null) {
  if (active === 'asc') return '↑';
  if (active === 'desc') return '↓';
  return '⇅';
}

export function DataTable<T>({
  items,
  keyOf,
  hrefOf,
  nameOf,
  columns,
  action,
  padded = true,
  scrollRows = true,
  style,
}: {
  items: T[];
  keyOf: (item: T) => string;
  /** 行的跳转目标：设置后名称列变成指向该路由的链接。 */
  hrefOf?: (item: T) => Href;
  /** 左侧列：基金名称加上下面那行小字。 */
  nameOf: (item: T) => { title: string; sub: string };
  columns: DataColumn<T>[];
  /** 尾部操作列；行内没有逐行操作时就不传。 */
  action?: { title: string; label: (item: T) => string; busy: (item: T) => boolean; onPress: (item: T) => void } | null;
  /** 表格没有被包在自带内边距的 Card 里时，用它补左右留白。 */
  padded?: boolean;
  /** 嵌在页面滚动容器里的表格不再自己滚行，改为按行数撑开。 */
  scrollRows?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const headRef = useRef<ScrollView>(null);
  const gridRef = useRef<ScrollView>(null);
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null);
  const columnKey = items.map(keyOf).join(',');
  const gridWidth = columns.reduce((total, column) => total + column.width, 0) + (action ? ACTION_W : 0);

  const sorted = (() => {
    if (sort === null) return items;
    const pick = columns.find((column) => column.key === sort.key)?.sortValue;
    if (!pick) return items;
    return [...items].sort((left, right) => {
      const a = pick(left);
      const b = pick(right);
      // 缺失的数字不等于 0：不论升序降序都排在最末尾。
      if (a === null || a === undefined) return b === null || b === undefined ? 0 : 1;
      if (b === null || b === undefined) return -1;
      const order =
        typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'zh');
      return sort.dir === 'asc' ? order : -order;
    });
  })();

  const toggleSort = (key: string) => {
    setSort((current) =>
      current && current.key === key ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    );
  };

  const sortableHeader = (key: string, title: string) => (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`按${title}排序`}
      onPress={() => toggleSort(key)}
      style={{ flexDirection: 'row', alignItems: 'center' }}
    >
      <Text style={{ fontSize: 12, color: sort?.key === key ? theme.text : theme.textMuted, fontWeight: '600' }} numberOfLines={1}>
        {title}
      </Text>
      <Text style={{ fontSize: 11, color: sort?.key === key ? theme.primary : theme.textFaint, marginLeft: 3 }}>
        {sortArrow(sort?.key === key ? sort.dir : null)}
      </Text>
    </Pressable>
  );

  useEffect(() => {
    // 表头是网格的镜像：换分组、删行导致数据整体替换时，若网格还停在
    // 旧偏移上，表头就会对错列，
    // 直到下一次滚动才纠正，所以这里先归零。
    gridRef.current?.scrollTo({ x: 0, y: 0, animated: false });
    headRef.current?.scrollTo({ x: 0, animated: false });
  }, [columnKey]);

  const followGrid = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    headRef.current?.scrollTo({ x: event.nativeEvent.contentOffset.x, animated: false });
  };

  const rows = (
    <View style={{ flexDirection: 'row' }}>
      <View style={{ width: NAME_W }}>
        {sorted.map((item) => {
          const name = nameOf(item);
          const content = (
            <>
              <Text style={{ fontSize: 14, color: theme.text, fontWeight: '500' }} numberOfLines={1}>
                {name.title}
              </Text>
              <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }} numberOfLines={1}>
                {name.sub}
              </Text>
            </>
          );
          return hrefOf ? (
            <Link key={keyOf(item)} href={hrefOf(item)} asChild>
              <Pressable accessibilityRole="link" accessibilityLabel={`查看 ${name.title}`} style={nameCellStyle}>
                {content}
              </Pressable>
            </Link>
          ) : (
            <View key={keyOf(item)} style={nameCellStyle}>
              {content}
            </View>
          );
        })}
      </View>

      <View style={{ flex: 1, overflow: 'hidden' }}>
        <ScrollView ref={gridRef} horizontal onScroll={followGrid} scrollEventThrottle={16} showsHorizontalScrollIndicator={false}>
          <View style={{ width: gridWidth }}>
            {sorted.map((item) => (
              <View
                key={keyOf(item)}
                style={{
                  flexDirection: 'row',
                  height: ROW_H,
                  alignItems: 'flex-start',
                  paddingTop: CELL_TOP,
                  borderBottomWidth: 1,
                  borderColor: theme.border,
                }}
              >
                {columns.map((column) => {
                  const cell = column.cell(item);
                  return (
                    <View key={column.key} style={{ width: column.width, paddingHorizontal: 6 }}>
                      <Text
                        style={{ fontSize: 13, color: cell.color ?? theme.text, textAlign: cell.align ?? 'left' }}
                        numberOfLines={1}
                      >
                        {cell.text}
                      </Text>
                      {cell.sub ? (
                        <Text style={{ fontSize: 11, color: cell.subColor ?? theme.textFaint, marginTop: 2 }} numberOfLines={1}>
                          {cell.sub}
                        </Text>
                      ) : null}
                    </View>
                  );
                })}
                {action ? (
                  <View style={{ width: ACTION_W, paddingHorizontal: 6 }}>
                    <Pressable
                      accessibilityRole="button"
                      accessibilityLabel={`${action.title} ${nameOf(item).title}`}
                      hitSlop={10}
                      disabled={action.busy(item)}
                      onPress={() => action.onPress(item)}
                      style={{ opacity: action.busy(item) ? 0.5 : 1 }}
                    >
                      <Text style={{ fontSize: 12, color: theme.danger }}>{action.label(item)}</Text>
                    </Pressable>
                  </View>
                ) : null}
              </View>
            ))}
          </View>
        </ScrollView>
      </View>
    </View>
  );

  const header = (
    <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.border }}>
      {/* 名称列不需要表头：每行本来就是基金名称加代码，
          上面再放个标题只是给同一个东西贴第二遍标签。 */}
      <View style={{ width: NAME_W }} />
      <View style={{ flex: 1, overflow: 'hidden' }}>
        <ScrollView ref={headRef} horizontal scrollEnabled={false} showsHorizontalScrollIndicator={false}>
          {columns.map((column) => (
            <View key={column.key} style={{ width: column.width, paddingVertical: 8, paddingHorizontal: 6 }}>
              {column.sortValue ? (
                sortableHeader(column.key, column.title)
              ) : (
                <Text style={{ fontSize: 12, color: theme.textMuted, fontWeight: '600' }} numberOfLines={1}>
                  {column.title}
                </Text>
              )}
            </View>
          ))}
          {action ? (
            <View style={{ width: ACTION_W, paddingVertical: 8, paddingHorizontal: 6 }}>
              <Text style={{ fontSize: 12, color: theme.textMuted, fontWeight: '600' }} numberOfLines={1}>
                {action.title}
              </Text>
            </View>
          ) : null}
        </ScrollView>
      </View>
    </View>
  );

  return (
    <View style={[{ backgroundColor: theme.surface }, padded ? { paddingHorizontal: theme.gap } : null, style]}>
      {header}
      {scrollRows ? <ScrollView>{rows}</ScrollView> : rows}
    </View>
  );
}
