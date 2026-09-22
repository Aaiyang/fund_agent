import { router } from 'expo-router';
import { useDeferredValue, useState } from 'react';
import { Text, TextInput, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { GroupPicker } from '@/components/GroupPicker';
import { theme } from '@/constants/theme';
import { useFundSearch } from '@/hooks/useFunds';
import { useAddWatchlistFund, useCreateWatchlistGroup, useWatchlist, useWatchlistGroups } from '@/hooks/useWatchlist';
import { formatNumber, formatReturnPoints } from '@/utils/format';

export default function SearchScreen() {
  const [keyword, setKeyword] = useState('');
  // Typing Chinese needs an IME commit; only query the settled text.
  const settledKeyword = useDeferredValue(keyword);
  const search = useFundSearch(settledKeyword);
  const watchlist = useWatchlist(null);
  const groups = useWatchlistGroups();
  const add = useAddWatchlistFund();
  const createGroup = useCreateWatchlistGroup();
  const [feedback, setFeedback] = useState<string | null>(null);
  const [picking, setPicking] = useState<{ code: string; name: string } | null>(null);

  const added = new Set((watchlist.data?.items ?? []).map((item) => item.fund_code));

  async function createGroupNamed(name: string): Promise<number | null> {
    try {
      const group = await createGroup.mutateAsync({ name });
      return group.id;
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : '分组创建失败');
      return null;
    }
  }

  return (
    <Screen>
      <Card>
        <TextInput
          value={keyword}
          onChangeText={setKeyword}
          placeholder="基金代码 / 名称 / 模糊关键词"
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
        {feedback ? <Text style={{ fontSize: 12, color: theme.primary, marginTop: 8 }}>{feedback}</Text> : null}
      </Card>

      <Card>
        <SectionTitle title={settledKeyword.trim() ? '搜索结果' : '输入关键词开始搜索'} />
        {!settledKeyword.trim() ? (
          <EmptyState title="支持代码与名称" hint="例如 011452、华泰柏瑞、创新药" />
        ) : (
          <Async
            query={search}
            empty={(data) => (data.items.length === 0 ? <EmptyState title="没有匹配到基金" hint="换个关键词试试" /> : null)}
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
                <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 10 }}>
                  净值示例：{formatNumber(data.items[0]?.latest_nav)} / {formatReturnPoints(data.items[0]?.daily_return)}
                </Text>
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
                setFeedback(`${target.code} 已加入自选${groupIds.length > 0 ? `与 ${groupIds.length} 个分组` : '（不分组）'}`),
              onError: (error) => setFeedback(error.message),
            },
          );
        }}
      />
    </Screen>
  );
}
