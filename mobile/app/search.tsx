import { router } from 'expo-router';
import { useDeferredValue, useState } from 'react';
import { Text, TextInput, View } from 'react-native';

import { Async, EmptyState, describeError } from '@/components/states';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { GroupPicker } from '@/components/GroupPicker';
import { theme } from '@/constants/theme';
import { useFundSearch } from '@/hooks/useFunds';
import { useAddWatchlistFund, useCreateWatchlistGroup, useWatchlist, useWatchlistGroups } from '@/hooks/useWatchlist';

export default function SearchScreen() {
  const [keyword, setKeyword] = useState('');
  // 输入中文得等输入法上屏；只对已经稳定的文本发起查询。
  const settledKeyword = useDeferredValue(keyword);
  const search = useFundSearch(settledKeyword);
  const watchlist = useWatchlist(null);
  const groups = useWatchlistGroups();
  const add = useAddWatchlistFund();
  const createGroup = useCreateWatchlistGroup();
  const [feedback, setFeedback] = useState<{ text: string; error: boolean } | null>(null);
  const [picking, setPicking] = useState<{ code: string; name: string } | null>(null);

  const added = new Set((watchlist.data?.items ?? []).map((item) => item.fund_code));

  async function createGroupNamed(name: string): Promise<number | null> {
    try {
      const group = await createGroup.mutateAsync({ name });
      return group.id;
    } catch (error) {
      setFeedback({ text: describeError(error), error: true });
      return null;
    }
  }

  const searching = Boolean(settledKeyword.trim());

  return (
    <Screen>
      <Card>
        <TextInput
          value={keyword}
          onChangeText={setKeyword}
          placeholder="请输入基金代码或名称"
          placeholderTextColor={theme.textFaint}
          autoCapitalize="none"
          style={{
            borderWidth: 1,
            borderColor: theme.border,
            borderRadius: 10,
            paddingHorizontal: 12,
            paddingVertical: 10,
            fontSize: 15,
            color: theme.text,
            backgroundColor: theme.surface,
          }}
        />
        {feedback ? (
          <Text style={{ fontSize: 12, color: feedback.error ? theme.danger : theme.primary, marginTop: 8 }}>
            {feedback.text}
          </Text>
        ) : null}
      </Card>

      <Card>
        <SectionTitle title={searching ? '搜索结果' : '搜索基金'} />
        {!searching ? (
          <EmptyState title="还没有搜索关键词" hint="输入 6 位基金代码或名称，例如 011452、华泰柏瑞" />
        ) : (
          <Async
            query={search}
            empty={(data) =>
              data.items.length === 0 ? <EmptyState title="还没有匹配的基金" hint="换个关键词，或输入 6 位基金代码" /> : null
            }
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
                    extra={item.fund_type ?? undefined}
                    badges={item.is_held ? [{ label: '持有', tone: 'muted' }] : []}
                    action={
                      item.is_watchlisted || added.has(item.fund_code)
                        ? { label: '已自选', tone: 'muted', onPress: () => router.push('/watchlist') }
                        : { label: '+ 自选', onPress: () => setPicking({ code: item.fund_code, name: item.fund_name }) }
                    }
                    pending={add.isPending}
                  />
                ))}
              </View>
            )}
          </Async>
        )}
      </Card>

      <GroupPicker
        visible={picking !== null}
        fundName={picking?.name ?? ''}
        groups={groups.data?.items ?? []}
        busy={add.isPending}
        onCreateGroup={createGroupNamed}
        onCancel={() => setPicking(null)}
        onConfirm={(groupIds) => {
          const target = picking;
          setPicking(null);
          if (!target) return;
          add.mutate(
            { fund_code: target.code, group_ids: groupIds },
            {
              onSuccess: () =>
                setFeedback({
                  text: `${target.code} 已加入自选${groupIds.length > 0 ? `与 ${groupIds.length} 个分组` : '（不分组）'}`,
                  error: false,
                }),
              onError: (error) => setFeedback({ text: describeError(error), error: true }),
            },
          );
        }}
      />
    </Screen>
  );
}
