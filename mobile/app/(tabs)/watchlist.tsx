import { SymbolView } from 'expo-symbols';
import { router } from 'expo-router';
import { useRef } from 'react';
import { Pressable, ScrollView, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { NavTab, Screen } from '@/components/ui';
import { WatchlistTable } from '@/components/WatchlistTable';
import { theme } from '@/constants/theme';
import { useDragScroll } from '@/hooks/useDragScroll';
import { useRemoveWatchlistFund, useWatchlist, useWatchlistGroups } from '@/hooks/useWatchlist';
import { estimatesByCode, useValuationEstimates } from '@/hooks/useValuation';
import { useUiStore } from '@/stores/ui';

export default function WatchlistScreen() {
  const groupId = useUiStore((state) => state.groupId);
  const setGroupId = useUiStore((state) => state.setGroupId);
  const list = useWatchlist(groupId);
  const valuations = useValuationEstimates((list.data?.items ?? []).map((item) => item.fund_code));
  const groups = useWatchlistGroups();
  const remove = useRemoveWatchlistFund();
  const groupsRef = useRef<ScrollView>(null);
  useDragScroll(groupsRef);

  return (
    <Screen scroll={false}>
      <View style={{ backgroundColor: theme.surface, padding: theme.gap, paddingBottom: 4 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <ScrollView
            ref={groupsRef}
            horizontal
            showsHorizontalScrollIndicator={false}
            style={{ flex: 1 }}
            contentContainerStyle={{ alignItems: 'center' }}
          >
            <NavTab label="全部" active={groupId === null} onPress={() => setGroupId(null)} />
            {(groups.data?.items ?? []).map((group) => (
              <NavTab
                key={group.id}
                label={`${group.name}(${group.fund_count})`}
                active={groupId === group.id}
                onPress={() => setGroupId(group.id)}
              />
            ))}
          </ScrollView>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="管理分组"
            hitSlop={10}
            onPress={() => router.push('/watchlist-groups')}
            style={({ pressed }) => [{ opacity: pressed ? 0.7 : 1 }]}
          >
            <SymbolView name={{ ios: 'gear', android: 'settings', web: 'settings' }} tintColor={theme.textMuted} size={18} />
          </Pressable>
        </View>
      </View>

      <View style={{ flex: 1 }}>
        <Async
          query={list}
          empty={(data) =>
            data.items.length === 0 ? <EmptyState title="还没有自选基金" hint="点右上角搜索图标，按代码或名称添加" /> : null
          }
        >
          {(data) => (
            <WatchlistTable
              items={data.items}
              onRemove={(fundCode) => remove.mutate(fundCode)}
              pendingCode={remove.variables ?? undefined}
              estimates={estimatesByCode(valuations.data?.items)}
            />
          )}
        </Async>
      </View>
    </Screen>
  );
}
