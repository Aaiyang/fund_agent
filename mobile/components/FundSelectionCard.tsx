import { ActivityIndicator, Pressable, Text, View } from 'react-native';

import { Button, Card } from '@/components/ui';
import { theme } from '@/constants/theme';
import type { ChatPendingAction } from '@/hooks/useChatImport';

export function FundSelectionCard({ action, busy, onSelect, onCancel }: {
  action: Extract<ChatPendingAction, { kind: 'fund_selection' }>;
  busy: boolean;
  onSelect: (fundCode: string) => void;
  onCancel: () => void;
}) {
  return (
    <Card>
      <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text }}>请选择要分析的基金</Text>
      <Text style={{ marginTop: 6, fontSize: 12, color: theme.textMuted }}>{action.notice}</Text>
      <View style={{ gap: 8, marginVertical: 12 }}>
        {action.candidates.map((fund) => (
          <Pressable key={fund.fund_code} accessibilityRole="button"
            accessibilityLabel={`分析${fund.fund_name}，代码${fund.fund_code}`}
            accessibilityState={{ disabled: busy }}
            disabled={busy} onPress={() => onSelect(fund.fund_code)}
            style={({ pressed }) => [
              { backgroundColor: theme.background, borderRadius: 8, padding: 10 },
              { opacity: busy ? 0.5 : pressed ? 0.85 : 1 },
            ]}>
            <Text style={{ fontSize: 14, color: theme.text }}>{fund.fund_name}</Text>
            <Text style={{ marginTop: 4, fontSize: 12, color: theme.primary }}>{fund.fund_code}{fund.fund_type ? ` · ${fund.fund_type}` : ''}</Text>
          </Pressable>
        ))}
      </View>
      {busy ? <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <ActivityIndicator color={theme.primary} /><Text style={{ fontSize: 12, color: theme.textMuted }}>正在继续分析…</Text>
      </View> : null}
      <Button label="都不是，重新输入名称" variant="secondary" disabled={busy} onPress={onCancel} />
    </Card>
  );
}
