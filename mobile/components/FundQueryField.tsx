/**
 * Fund input for manual entry: code and name share one box, and the provider's
 * fuzzy search offers pickable matches so the row can submit a real code
 * instead of a name the backend has to resolve later.
 */

import { useDeferredValue } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

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
  /** Code already resolved from a pick; shown as a confirmation line. */
  matchedCode?: string | null;
}) {
  // Typing Chinese needs an IME commit; only query the settled text.
  const settled = useDeferredValue(value);
  const search = useFundSearch(settled);
  const keyword = settled.trim();
  // Gated on the text, never on focus: a tap blurs the input, and a list that
  // unmounted on blur would swallow the press that selects the suggestion.
  const showList = keyword.length > 0 && !matchedCode;
  const suggestions = showList ? (search.data?.items ?? []).slice(0, MAX_SUGGESTIONS) : [];

  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 6 }}>{label}</Text>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder="基金代码 / 名称 / 模糊关键词"
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
              {search.isFetching ? '搜索中…' : '没有匹配项，也可直接提交，由后端识别'}
            </Text>
          ) : null}
          {suggestions.map((item) => (
            <Pressable
              key={item.fund_code}
              accessibilityRole="button"
              onPress={() => onPick({ code: item.fund_code, name: item.fund_name })}
              style={{ paddingVertical: 8, borderTopWidth: 1, borderColor: theme.border }}
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
