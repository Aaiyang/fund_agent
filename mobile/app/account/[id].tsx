import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { Async, EmptyState, describeError } from '@/components/states';
import { Button, Card, Field, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useAccounts, usePositions, useUpdateAccount } from '@/hooks/usePortfolio';
import { formatDateTime, formatRate } from '@/utils/format';

/** 单个账户：改名、查看该账户的持仓与最近一次导入（spec 3.6）。 */
export default function AccountDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const accountId = Number(id);
  const accounts = useAccounts();
  const positions = usePositions(accountId);
  const update = useUpdateAccount();
  const account = accounts.data?.items.find((item) => item.id === accountId);
  const [name, setName] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function rename() {
    if (!account) return;
    const trimmed = (name ?? account.name).trim();
    if (!trimmed) {
      setProblem('请填写账户名称');
      return;
    }
    const taken = (accounts.data?.items ?? []).some(
      (other) => other.id !== accountId && other.name.trim().toLowerCase() === trimmed.toLowerCase(),
    );
    if (taken) {
      setProblem('该账户名称已存在');
      return;
    }
    setProblem(null);
    update.mutate(
      { accountId, name: trimmed },
      {
        onSuccess: () => setName(null),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <Card>
          <SectionTitle title={account?.name ?? `账户 #${accountId}`} />
          <Text style={{ fontSize: 12, color: theme.textMuted }}>
            创建 {formatDateTime(account?.created_at)} · 最近导入 {formatDateTime(account?.last_imported_at)}
          </Text>
          <Field label="账户名称" value={name ?? account?.name ?? ''} onChangeText={setName} placeholder="请输入账户名称" />
          {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
          <Button
            label="保存改名"
            variant="secondary"
            loading={update.isPending}
            disabled={!account || !name?.trim()}
            onPress={rename}
          />
        </Card>

        <Card>
          <SectionTitle title="该账户持仓" action="返回账户列表" onAction={() => router.back()} />
          <Async
            query={positions}
            empty={(data) =>
              data.items.length === 0 ? <EmptyState title="还没有持仓" hint="可手动录入或用截图导入" /> : null
            }
          >
            {(data) => (
              <View>
                {data.items.map((position) => (
                  <FundRow
                    key={position.fund_code}
                    fundCode={position.fund_code}
                    fundName={position.fund_name ?? position.fund_code}
                    latestNav={position.market_value}
                    dailyReturn={position.daily_return}
                    navDate={position.nav_date}
                    extra={`占比 ${formatRate(position.position_ratio)}`}
                  />
                ))}
              </View>
            )}
          </Async>
        </Card>
      </Screen>
    </KeyboardAvoidingView>
  );
}
