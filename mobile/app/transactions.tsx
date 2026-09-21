import { useLocalSearchParams } from 'expo-router';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Badge, Card, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAccounts, useTransactions } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import { formatDate, formatMoney, formatNumber } from '@/utils/format';

const TYPE_LABEL: Record<string, string> = {
  BUY: '买入',
  SELL: '卖出',
  DIVIDEND: '分红',
  IMPORT_ADJUSTMENT: '导入修正',
  MANUAL_ADJUSTMENT: '手工修正',
};

/** Transaction and adjustment history (spec 3.8). */
export default function TransactionsScreen() {
  const params = useLocalSearchParams<{ fund_code?: string; account_id?: string }>();
  const uiAccount = useUiStore((state) => state.accountId);
  const accounts = useAccounts();
  const accountId = params.account_id ? Number(params.account_id) : uiAccount;
  const transactions = useTransactions(accountId, params.fund_code ?? null);

  return (
    <Screen>
      <Card>
        <SectionTitle title="交易 / 调整记录" />
        <Text style={{ fontSize: 12, color: theme.textMuted }}>
          范围：{params.fund_code ? `基金 ${params.fund_code}` : '全部基金'} ·{' '}
          {accountId ? `账户 ${accounts.data?.items.find((item) => item.id === accountId)?.name ?? accountId}` : '全部账户'}
        </Text>
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 6 }}>
          导入与手工修正都是审计型调整记录，不代表真实买卖流水；第一阶段不提供交易下单。
        </Text>
      </Card>

      <Card>
        <Async
          query={transactions}
          empty={(data) => (data.items.length === 0 ? <EmptyState title="暂无记录" hint="录入或确认导入持仓后会生成调整记录" /> : null)}
        >
          {(data) => (
            <View>
              {data.items.map((item) => (
                <View key={item.id} style={{ paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.border }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={{ fontSize: 15, color: theme.text, flex: 1 }} numberOfLines={1}>
                      {item.fund_name ?? item.fund_code}
                    </Text>
                    <Badge
                      label={TYPE_LABEL[item.transaction_type] ?? item.transaction_type}
                      tone={item.transaction_type === 'IMPORT_ADJUSTMENT' ? 'warning' : 'muted'}
                    />
                  </View>
                  <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 4 }}>
                    {formatDate(item.trade_date)} · 份额 {formatNumber(item.shares)} · 净值 {formatNumber(item.nav)} · 金额{' '}
                    {formatMoney(item.amount)}
                    {item.fee !== null && item.fee !== undefined ? ` · 费用 ${formatMoney(item.fee)}` : ''}
                  </Text>
                  <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
                    来源 {item.source}
                    {item.external_transaction_id ? ` · 导入批次 ${item.external_transaction_id.slice(0, 8)}…` : ''}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </Async>
      </Card>
    </Screen>
  );
}
