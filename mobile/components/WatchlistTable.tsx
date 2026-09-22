/**
 * Watchlist data grid: the header row and the fund column stay put while the
 * metric columns slide sideways as one block.
 *
 * Per-row horizontal scrollers would let each row drift to its own offset, so
 * the whole right side is a single scroller and the header mirrors it with a
 * `scrollEnabled={false}` replica.
 */

import { Link } from 'expo-router';
import { useRef } from 'react';
import {
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  Text,
  View,
} from 'react-native';

import { theme } from '@/constants/theme';
import type { WatchlistFund } from '@/hooks/useWatchlist';
import { formatDate, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

const NAME_W = 132;
const ACTION_W = 56;
const ROW_H = 58;

type Column = {
  key: string;
  title: string;
  width: number;
  cell: (item: WatchlistFund) => { text: string; color?: string };
};

const COLUMNS: Column[] = [
  { key: 'nav', title: '最新净值', width: 80, cell: (item) => ({ text: formatNumber(item.latest_nav) }) },
  {
    key: 'daily',
    title: '日涨跌',
    width: 76,
    cell: (item) => ({ text: formatReturnPoints(item.daily_return), color: trendColor(item.daily_return) }),
  },
  {
    key: 'weekly',
    title: '近1周',
    width: 76,
    cell: (item) => ({ text: formatReturnPoints(item.weekly_return), color: trendColor(item.weekly_return) }),
  },
  {
    key: 'monthly',
    title: '近1月',
    width: 76,
    cell: (item) => ({ text: formatReturnPoints(item.monthly_return), color: trendColor(item.monthly_return) }),
  },
  {
    key: 'navDate',
    title: '净值日期',
    width: 88,
    cell: (item) => ({ text: formatDate(item.nav_date), color: item.is_updated ? theme.text : theme.warning }),
  },
];

const GRID_W = COLUMNS.reduce((total, column) => total + column.width, 0) + ACTION_W;

const headerTextStyle = { fontSize: 12, color: theme.textMuted, fontWeight: '600' as const };
const cellTextStyle = { fontSize: 13, color: theme.text };

export function WatchlistTable({
  items,
  onRemove,
  pendingCode,
}: {
  items: WatchlistFund[];
  onRemove: (fundCode: string) => void;
  pendingCode?: string;
}) {
  const headRef = useRef<ScrollView>(null);

  const followGrid = (event: NativeSyntheticEvent<NativeScrollEvent>) => {
    headRef.current?.scrollTo({ x: event.nativeEvent.contentOffset.x, animated: false });
  };

  return (
    <View style={{ flex: 1, backgroundColor: theme.surface }}>
      <View style={{ flexDirection: 'row', borderBottomWidth: 1, borderColor: theme.border }}>
        <View style={{ width: NAME_W, paddingVertical: 8, paddingEnd: 8 }}>
          <Text style={headerTextStyle}>基金</Text>
        </View>
        <View style={{ flex: 1, overflow: 'hidden' }}>
          <ScrollView ref={headRef} horizontal scrollEnabled={false} showsHorizontalScrollIndicator={false}>
            {COLUMNS.map((column) => (
              <View key={column.key} style={{ width: column.width, paddingVertical: 8, paddingHorizontal: 6 }}>
                <Text style={headerTextStyle} numberOfLines={1}>
                  {column.title}
                </Text>
              </View>
            ))}
            <View style={{ width: ACTION_W, paddingVertical: 8, paddingHorizontal: 6 }}>
              <Text style={headerTextStyle} numberOfLines={1}>
                操作
              </Text>
            </View>
          </ScrollView>
        </View>
      </View>

      <ScrollView>
        <View style={{ flexDirection: 'row' }}>
          <View style={{ width: NAME_W }}>
            {items.map((item) => (
              <Link
                key={item.fund_code}
                href={{ pathname: '/fund/[code]', params: { code: item.fund_code } }}
                asChild
              >
                <Pressable
                  accessibilityRole="link"
                  accessibilityLabel={`查看 ${item.fund_name}`}
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
                    {item.fund_name}
                  </Text>
                  <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }} numberOfLines={1}>
                    {item.fund_code}
                    {item.is_held ? ' · 持有' : ''}
                    {(item.groups ?? []).length > 0 ? ` · ${(item.groups ?? []).join('/')}` : ''}
                  </Text>
                </Pressable>
              </Link>
            ))}
          </View>

          <View style={{ flex: 1, overflow: 'hidden' }}>
            <ScrollView horizontal onScroll={followGrid} scrollEventThrottle={16} showsHorizontalScrollIndicator={false}>
              <View style={{ width: GRID_W }}>
                {items.map((item) => (
                  <View
                    key={item.fund_code}
                    style={{
                      flexDirection: 'row',
                      height: ROW_H,
                      alignItems: 'center',
                      borderBottomWidth: 1,
                      borderColor: theme.border,
                    }}
                  >
                    {COLUMNS.map((column) => {
                      const cell = column.cell(item);
                      return (
                        <View key={column.key} style={{ width: column.width, paddingHorizontal: 6 }}>
                          <Text style={{ ...cellTextStyle, color: cell.color ?? theme.text }} numberOfLines={1}>
                            {cell.text}
                          </Text>
                        </View>
                      );
                    })}
                    <View style={{ width: ACTION_W, paddingHorizontal: 6 }}>
                      <Pressable
                        accessibilityRole="button"
                        accessibilityLabel={`删除自选 ${item.fund_name}`}
                        hitSlop={10}
                        disabled={pendingCode === item.fund_code}
                        onPress={() => onRemove(item.fund_code)}
                        style={{ opacity: pendingCode === item.fund_code ? 0.5 : 1 }}
                      >
                        <Text style={{ fontSize: 12, color: theme.danger }}>
                          {pendingCode === item.fund_code ? '删除中' : '删除'}
                        </Text>
                      </Pressable>
                    </View>
                  </View>
                ))}
              </View>
            </ScrollView>
          </View>
        </View>
      </ScrollView>

      <Text style={{ fontSize: 11, color: theme.textFaint, padding: 8 }}>
        左右滑动查看其它列 · 净值日期为橙色表示尚未更新
      </Text>
    </View>
  );
}
