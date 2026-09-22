import { router } from 'expo-router';
import { Pressable, ScrollView, Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Chip, Screen, SectionTitle } from '@/components/ui';
import { WatchlistTable } from '@/components/WatchlistTable';
import { theme } from '@/constants/theme';
import { useRemoveWatchlistFund, useWatchlist, useWatchlistGroups } from '@/hooks/useWatchlist';
import { useUiStore } from '@/stores/ui';

export default function WatchlistScreen() {
  const groupId = useUiStore((state) => state.groupId);
  const setGroupId = useUiStore((state) => state.setGroupId);
  const list = useWatchlist(groupId);
  const groups = useWatchlistGroups();
  const remove = useRemoveWatchlistFund();

  return (
    <Screen scroll={false}>
      <View style={{ backgroundColor: theme.surface, padding: theme.gap, paddingBottom: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <SectionTitle title={`自选列表（${list.data?.total ?? 0}）`} />
          <Pressable accessibilityRole="button" hitSlop={8} onPress={() => router.push('/watchlist-groups')}>
            <Text style={{ color: theme.primary, fontSize: 13 }}>管理分组</Text>
          </Pressable>
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ alignItems: 'center' }}>
          <Chip label="全部" active={groupId === null} onPress={() => setGroupId(null)} />
          {(groups.data?.items ?? []).map((group) => (
            <Chip
              key={group.id}
              label={`${group.name}(${group.fund_count})`}
              active={groupId === group.id}
              onPress={() => setGroupId(group.id)}
            />
          ))}
        </ScrollView>
      </View>

      <View style={{ flex: 1 }}>
        <Async
          query={list}
          empty={(data) =>
            data.items.length === 0 ? <EmptyState title="还没有自选基金" hint="点右上角搜索图标按代码或名称添加" /> : null
          }
        >
          {(data) => (
            <WatchlistTable
              items={data.items}
              onRemove={(fundCode) => remove.mutate(fundCode)}
              pendingCode={remove.variables ?? undefined}
            />
          )}
        </Async>
      </View>
    </Screen>
  );
}
