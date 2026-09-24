import { router } from 'expo-router';
import { useState } from 'react';
import { Text } from 'react-native';

import { Button, Card, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useAccounts, useCreateAccount } from '@/hooks/usePortfolio';

/** Create a portfolio account. Only the name is asked for (spec 3.6). */
export default function AccountAddScreen() {
  const create = useCreateAccount();
  const accounts = useAccounts();
  const [name, setName] = useState('');
  const [problem, setProblem] = useState<string | null>(null);

  function submit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setProblem('请输入账户名称');
      return;
    }
    // The backend enforces this too; checking the loaded list gives the answer
    // without a round trip.
    const taken = (accounts.data?.items ?? []).some((account) => account.name.trim().toLowerCase() === trimmed.toLowerCase());
    if (taken) {
      setProblem('该账户名称已存在');
      return;
    }
    setProblem(null);
    create.mutate(
      { name: trimmed, account_type: 'manual', import_mode: 'manual' },
      {
        onSuccess: () => router.back(),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <Screen>
      <Card>
        <SectionTitle title="账户信息" />
        <Field label="账户名称" value={name} onChangeText={setName} placeholder="请输入账户名称" />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
        <Button label="创建账户" onPress={submit} loading={create.isPending} />
      </Card>
    </Screen>
  );
}
