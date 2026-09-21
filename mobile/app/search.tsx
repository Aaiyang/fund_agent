import { router } from 'expo-router';
import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Card, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useFundSearch } from '@/hooks/useFunds';
import { useAddWatchlistFund, useWatchlist } from '@/hooks/useWatchlist';
import { useUiStore } from '@/stores/ui';
import { formatNumber, formatReturnPoints } from '@/utils/format';

export default function SearchScreen() {
  const [keyword, setKeyword] = useState('');
  const groupId = useUiStore((state) => state.groupId);
  const search = useFundSearch(keyword);
  const watchlist = useWatchlist(null);
  const add = useAddWatchlistFund();
  const [feedback, setFeedback] = useState<string | null>(null);

  const added = new Set((watchlist.data?.items ?? []).map((item) => item.fund_code));

  function addToWatchlist(fundCode: string) {
    setFeedback(null);
    add.mutate(
      { fund_code: fundCode, group_ids: groupId ? [groupId] : [] },
      {
        onSuccess: () => setFeedback(`${fundCode} 已加入自选${groupId ? '并加入当前分组' : ''}`),
        onError: (error) => setFeedback(error.message),
      },
    );
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
        {groupId ? (
          <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 8 }}>
            当前分组已选中：加入自选时会同时加入该分组
          </Text>
        ) : null}
        {feedback ? <Text style={{ fontSize: 12, color: theme.primary, marginTop: 8 }}>{feedback}</Text> : null}
      </Card>

      <Card>
        <SectionTitle title={keyword.trim() ? '搜索结果' : '输入关键词开始搜索'} />
        {!keyword.trim() ? (
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
                        : { label: '+ 自选', onPress: () => addToWatchlist(item.fund_code) }
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
    </Screen>
  );
}
