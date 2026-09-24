/**
 * Fixed-name-column data grid with one horizontally scrolling block of metric
 * columns, shared by 自选 and 持仓 so both read the same way.
 *
 * Per-row horizontal scrollers would let each row drift to its own offset, so
 * the whole right side is a single scroller and the header mirrors it with a
 * `scrollEnabled={false}` replica.
 */

import { Link } from 'expo-router';
import { type StyleProp, type ViewStyle, type NativeScrollEvent, type NativeSyntheticEvent, Pressable, ScrollView, Text, View } from 'react-native';
import { useEffect, useRef } from 'react';

import { theme } from '@/constants/theme';

const NAME_W = 132;
const ACTION_W = 56;
const ROW_H = 58;

export type DataCell = { text: string; color?: string; sub?: string; subColor?: string };

export type DataColumn<T> = {
  key: string;
  title: string;
  width: number;
  cell: (item: T) => DataCell;
};

export function DataTable<T>({
  items,
  keyOf,
  fundCodeOf,
  nameOf,
  columns,
  action,
  hint,
  padded = true,
  scrollRows = true,
  style,
}: {
  items: T[];
  keyOf: (item: T) => string;
  /** Row target: the grid always links to the fund detail page. */
  fundCodeOf: (item: T) => string;
  /** Left column: fund name plus the small line under it. */
  nameOf: (item: T) => { title: string; sub: string };
  columns: DataColumn<T>[];
  /** Trailing column; omit it when the rows have no per-row command. */
  action?: { title: string; label: (item: T) => string; busy: (item: T) => boolean; onPress: (item: T) => void } | null;
  hint: string;
  /** Horizontal inset for grids that are not already inside a padded Card. */
  padded?: boolean;
  /** Grids living inside a page scroller size to their rows instead. */
  scrollRows?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const headRef = useRef<ScrollView>(null);
  const gridRef = useRef<ScrollView>(null);
  const columnKey = items.map(keyOf).join(',');
  const gridWidth = columns.reduce((total, column) => total + column.width, 0) + (action ? ACTION_W : 0);

  useEffect(() => {
    // The header mirrors the grid, so a grid that keeps its offset while the
    // rows are replaced (group switch, delete) leaves titles over the wrong
    // columns until the next scroll.
    gridRef.current?.scrollTo({ x: 0, y: 0, animated: false });
    headRef.current?.scrollTo({ x: 0, animated: false });
  }, [columnKey]);

  const followGrid = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    headRef.current?.scrollTo({ x: event.nativeEvent.contentOffset.x, animated: false });
  };

  const rows = (
    <View style={{ flexDirection: 'row' }}>
      <View style={{ width: NAME_W }}>
        {items.map((item) => (
          <Link
            key={keyOf(item)}
            href={{ pathname: '/fund/[code]', params: { code: fundCodeOf(item) } }}
            asChild
          >
            <Pressable
              accessibilityRole="link"
              accessibilityLabel={`查看 ${nameOf(item).title}`}
              style={{
                width: NAME_W,
                height: ROW_H,
                justifyContent: 'center',
                paddingEnd: 8,
                borderBottomWidth: 1,
                borderColor: theme.border,
              }}
            >
              <Text style={{ fontSize: 14, color: theme.text, fontWeight: '500' }} numberOfLines={1}>
                {nameOf(item).title}
              </Text>
              <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }} numberOfLines={1}>
                {nameOf(item).sub}
              </Text>
            </Pressable>
          </Link>
        ))}
      </View>

      <View style={{ flex: 1, overflow: 'hidden' }}>
        <ScrollView ref={gridRef} horizontal onScroll={followGrid} scrollEventThrottle={16} showsHorizontalScrollIndicator={false}>
          <View style={{ width: gridWidth }}>
            {items.map((item) => (
              <View
                key={keyOf(item)}
                style={{
                  flexDirection: 'row',
                  height: ROW_H,
                  alignItems: 'center',
                  borderBottomWidth: 1,
                  borderColor: theme.border,
                }}
              >
                {columns.map((column) => {
                  const cell = column.cell(item);
                  return (
                    <View key={column.key} style={{ width: column.width, paddingHorizontal: 6 }}>
                      <Text style={{ fontSize: 13, color: cell.color ?? theme.text }} numberOfLines={1}>
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
      <View style={{ width: NAME_W, paddingVertical: 8, paddingEnd: 8 }}>
        <Text style={{ fontSize: 12, color: theme.textMuted, fontWeight: '600' }}>基金</Text>
      </View>
      <View style={{ flex: 1, overflow: 'hidden' }}>
        <ScrollView ref={headRef} horizontal scrollEnabled={false} showsHorizontalScrollIndicator={false}>
          {columns.map((column) => (
            <View key={column.key} style={{ width: column.width, paddingVertical: 8, paddingHorizontal: 6 }}>
              <Text style={{ fontSize: 12, color: theme.textMuted, fontWeight: '600' }} numberOfLines={1}>
                {column.title}
              </Text>
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
      <Text style={{ fontSize: 11, color: theme.textFaint, paddingVertical: 8 }}>{hint}</Text>
    </View>
  );
}
