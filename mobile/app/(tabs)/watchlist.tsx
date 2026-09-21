import { router } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Button, Card, Chip, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useRemoveWatchlistFund, useWatchlist, useWatchlistGroups } from '@/hooks/useWatchlist';
import { useUiStore } from '@/stores/ui';
import { formatNumber, formatReturnPoints } from '@/utils/format';

export default function WatchlistScreen() {
  const groupId = useUiStore((state) => state.groupId);
  const setGroupId = useUiStore((state) => state.setGroupId);
  const list = useWatchlist(groupId);
  const groups = useWatchlistGroups();
  const remove = useRemoveWatchlistFund();

  return (
    <Screen>
      <Card>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <SectionTitle title="自选分组" />
          <Pressable onPress={() => router.push('/watchlist-groups')}>
            <Text style={{ color: theme.primary, fontSize: 13, marginBottom: 8 }}>管理分组</Text>
          </Pressable>
        </View>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          <Chip label="全部" active={groupId === null} onPress={() => setGroupId(null)} />
          {(groups.data?.items ?? []).map((group) => (
            <Chip key={group.id} label={`${group.name}(${group.fund_count})`} active={groupId === group.id} onPress={() => setGroupId(group.id)} />
          ))}
        </View>
        <Button label="搜索基金" variant="secondary" onPress={() => router.push('/search')} />
      </Card>

      <Card>
        <SectionTitle title={`自选列表（${list.data?.total ?? 0}）`} />
        <Async
          query={list}
          empty={(data) => (data.items.length === 0 ? <EmptyState title="还没有自选基金" hint="点击“搜索基金”按代码或名称添加" /> : null)}
        >
          {(data) => (
            <View>
              {data.items.map((item) => (
                <FundRow
                  key={item.fund_code}
                  fundCode={item.fund_code}
                  fundName={item.fund_name}
                  latestNav={item.latest_nav}
                  dailyReturn={item.daily_return}
                  navDate={item.nav_date}
                  extra={item.is_held ? '已持有' : undefined}
                  badges={[
                    ...(item.is_held ? [{ label: '持有', tone: 'muted' as const }] : []),
                    ...(item.groups ?? []).map((name) => ({ label: name, tone: 'muted' as const })),
                    ...(item.is_updated ? [] : [{ label: '净值未更新', tone: 'muted' as const }]),
                  ]}
                  action={{
                    label: remove.isPending ? '删除中…' : '删除',
                    tone: 'danger',
                    onPress: () => remove.mutate(item.fund_code),
                  }}
                />
              ))}
              <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 10 }}>
                最新净值 {formatNumber(data.items[0]?.latest_nav)}，涨跌 {formatReturnPoints(data.items[0]?.daily_return)}
              </Text>
            </View>
          )}
        </Async>
      </Card>
    </Screen>
  );
}
