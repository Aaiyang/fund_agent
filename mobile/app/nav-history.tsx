/**
 * 全量净值历史的分页列表：首屏给最新 30 条，滚到底部再拉更早的页，
 * 这样即便基金有十几年的记录也不会一次性全部渲染。
 */

import { useLocalSearchParams } from 'expo-router';
import { FlatList, Text, View } from 'react-native';

import { EmptyState, ErrorState, LoadingState, describeError } from '@/components/states';
import { Card, Screen } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useFundNavPages } from '@/hooks/useFunds';
import { formatDate, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

export default function NavHistoryScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const pages = useFundNavPages(code ?? null);
  // 每页返回时按日期升序；逐页各自倒序、页序保持不变，
  // 拼出来就是最新在前的一列，省掉对整份数据再排一次序。
  const rows = pages.data?.pages.flatMap((page) => [...page.points].reverse()) ?? [];
  const total = pages.data?.pages[0]?.total ?? 0;

  return (
    <Screen scroll={false}>
      <Card>
        <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text }}>
          净值明细{total ? `（${total}）` : ''}
        </Text>
        <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 2 }}>
          {code ? `基金 ${code}` : ''} · 每次加载 30 条
        </Text>
        {pages.isError ? (
          <ErrorState message={describeError(pages.error)} onRetry={() => void pages.refetch()} />
        ) : null}
        <View
          style={{
            flexDirection: 'row',
            marginTop: 12,
            paddingBottom: 6,
            borderBottomWidth: 1,
            borderColor: theme.border,
          }}
        >
          <Text style={{ flex: 1, fontSize: 12, color: theme.textMuted }}>日期</Text>
          <Text style={{ width: 88, fontSize: 12, color: theme.textMuted, textAlign: 'right' }}>净值</Text>
          <Text style={{ width: 76, fontSize: 12, color: theme.textMuted, textAlign: 'right' }}>日涨幅</Text>
        </View>
      </Card>

      <FlatList
        style={{ flex: 1 }}
        data={rows}
        keyExtractor={(item) => item.nav_date}
        renderItem={({ item }) => (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              paddingHorizontal: theme.gap,
              paddingVertical: 11,
              borderBottomWidth: 1,
              borderColor: theme.border,
            }}
          >
            <Text style={{ flex: 1, fontSize: 14, color: theme.text }}>{formatDate(item.nav_date)}</Text>
            <Text style={{ width: 88, fontSize: 14, color: theme.text, textAlign: 'right' }}>
              {formatNumber(item.unit_nav)}
            </Text>
            <Text style={{ width: 76, fontSize: 14, textAlign: 'right', color: trendColor(item.daily_return) }}>
              {formatReturnPoints(item.daily_return)}
            </Text>
          </View>
        )}
        ListEmptyComponent={
          pages.isPending ? (
            <LoadingState />
          ) : pages.isError ? null : (
            <EmptyState title="还没有净值记录" hint="返回基金详情下拉刷新可触发同步" />
          )
        }
        onEndReached={() => {
          if (pages.hasNextPage && !pages.isFetchingNextPage) void pages.fetchNextPage();
        }}
        onEndReachedThreshold={0.4}
        ListFooterComponent={
          <View style={{ paddingVertical: 16, alignItems: 'center' }}>
            {pages.isFetchingNextPage ? (
              <Text style={{ fontSize: 12, color: theme.textMuted }}>加载中…</Text>
            ) : rows.length && !pages.hasNextPage ? (
              <Text style={{ fontSize: 11, color: theme.textFaint }}>已到最早一条</Text>
            ) : null}
          </View>
        }
      />
    </Screen>
  );
}
