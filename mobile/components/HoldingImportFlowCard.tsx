import { ActivityIndicator, Text, View } from 'react-native';

import type { ChatImportAction } from '@/hooks/useChatImport';
import { ImportReviewCard } from '@/components/ImportReviewCard';
import { Button, Card } from '@/components/ui';
import { theme } from '@/constants/theme';

export function HoldingImportFlowCard({ action, busy, decision, onAccount, onContinue, onDecide }: {
  action: ChatImportAction;
  busy: boolean;
  decision: 'confirm' | 'cancel' | null;
  onAccount: (accountId: number) => void;
  onContinue: () => void;
  onDecide: (decision: 'confirm' | 'cancel') => void;
}) {
  if (action.kind === 'holding_import_review') {
    return <ImportReviewCard review={action} pending={decision} onDecide={onDecide} />;
  }
  return (
    <Card>
      <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text, marginBottom: 8 }}>
        {action.kind === 'holding_import_processing' ? '正在识别持仓截图' : '同步到哪个持仓账户？'}
      </Text>
      <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20 }}>{action.notice}</Text>
      {action.kind === 'holding_import_processing' ? (
        <View style={{ gap: 8, marginTop: 12 }}>
          <ActivityIndicator color={theme.primary} />
          <Button label="检查识别结果" variant="secondary" loading={busy} onPress={onContinue} />
        </View>
      ) : (
        <View style={{ gap: 8, marginTop: 12 }}>
          {action.accounts.map((account) => (
            <Button key={account.id} label={account.name} variant="secondary" disabled={busy} onPress={() => onAccount(account.id)} />
          ))}
        </View>
      )}
      <View style={{ marginTop: 12 }}>
        <Button label="取消这次导入" variant="secondary" disabled={busy} loading={decision === 'cancel'} onPress={() => onDecide('cancel')} />
      </View>
      <Text style={{ marginTop: 8, fontSize: 12, color: theme.textFaint }}>识别和选择账户不会修改持仓，复核后确认才会应用。</Text>
    </Card>
  );
}
