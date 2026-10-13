/**
 * 手动录入用的基金输入框：代码与名称共用一个输入框，数据源的模糊搜索
 * 给出可点选的匹配项，让这一行尽量提交真实代码，而不是留给后端再解析的名称。
 */

import { useDeferredValue } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useFundSearch } from '@/hooks/useFunds';

const MAX_SUGGESTIONS = 5;

export function FundQueryField({
  label,
  value,
  onChangeText,
  onPick,
  matchedCode,
}: {
  label: string;
  value: string;
  onChangeText: (text: string) => void;
  onPick: (fund: { code: string; name: string }) => void;
  /** 已从点选项中确定的代码，用来显示一行确认信息。 */
  matchedCode?: string | null;
}) {
  // 输入中文得等输入法上屏；只对已经稳定的文本发起查询。
  const settled = useDeferredValue(value);
  const search = useFundSearch(settled);
  const keyword = settled.trim();
  // 候选列表只看文本、不看焦点：点选会让输入框失焦，若列表在失焦时
  // 卸载，选中候选的那一下点击就被吞掉了。
  const showList = keyword.length > 0 && !matchedCode;
  const suggestions = showList ? (search.data?.items ?? []).slice(0, MAX_SUGGESTIONS) : [];

  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 6 }}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder="请输入基金代码或名称"
        placeholderTextColor={theme.textFaint}
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
      {matchedCode ? (
        <Text style={{ fontSize: 12, color: theme.primary, marginTop: 6 }}>已匹配 {matchedCode}</Text>
      ) : null}
      {showList ? (
        <View style={{ marginTop: 6 }}>
          {suggestions.length === 0 ? (
            <Text style={{ fontSize: 12, color: theme.textFaint }}>
              {search.isFetching
                ? '搜索中…'
                : search.isError
                  ? `${describeError(search.error)}，也可以直接提交`
                  : '还没有匹配项，也可以直接提交'}
            </Text>
          ) : null}
          {suggestions.map((item) => (
            <Pressable
              key={item.fund_code}
              accessibilityRole="button"
              accessibilityLabel={`选择${item.fund_name}，代码${item.fund_code}`}
              hitSlop={8}
              onPress={() => onPick({ code: item.fund_code, name: item.fund_name })}
              style={({ pressed }) => [
                {
                  paddingVertical: 8,
                  borderTopWidth: 1,
                  borderColor: theme.border,
                  opacity: pressed ? 0.85 : 1,
                },
              ]}
            >
              <Text style={{ fontSize: 14, color: theme.text }} numberOfLines={1}>
                {item.fund_name}
              </Text>
              <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
                {item.fund_code}
                {item.fund_type ? ` · ${item.fund_type}` : ''}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}
