import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Button, Card, Field, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useAccounts, usePositions, useUpdateAccount } from '@/hooks/usePortfolio';
import { formatDateTime, formatRate } from '@/utils/format';

/** One account: rename, review its holdings and last import (spec 3.6). */
export default function AccountDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const accountId = Number(id);
  const accounts = useAccounts();
  const positions = usePositions(accountId);
  const update = useUpdateAccount();
  const account = accounts.data?.items.find((item) => item.id === accountId);
  const [name, setName] = useState<string | null>(null);

  return (
    <Screen>
      <Card>
        <SectionTitle title={account?.name ?? `账户 #${accountId}`} />
        <Text style={{ fontSize: 12, color: theme.textMuted }}>
          来源标签 {account?.source_app ?? '--'} · 创建 {formatDateTime(account?.created_at)} · 最近导入{' '}
          {formatDateTime(account?.last_imported_at)}
        </Text>
        <Field label="账户名称" value={name ?? account?.name ?? ''} onChangeText={setName} />
        <Button
          label="保存改名"
          variant="secondary"
          loading={update.isPending}
          disabled={!account || !name}
          onPress={() => {
            if (!account) return;
            update.mutate(
              { accountId, name: (name ?? account.name).trim() },
              { onSuccess: () => setName(null) },
            );
          }}
        />
      </Card>

      <Card>
        <SectionTitle title="该账户持仓" action="返回账户列表" onAction={() => router.back()} />
        <Async
          query={positions}
          empty={(data) => (data.items.length === 0 ? <EmptyState title="该账户暂无持仓" hint="可手动录入或用截图导入" /> : null)}
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
  );
}
