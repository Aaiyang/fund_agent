import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useCreateAccount } from '@/hooks/usePortfolio';

const SOURCE_LABELS = ['支付宝', '天天基金', '银行', '手工账户'];

/** Create a portfolio account. source_app is a label, never a connection (spec 3.6). */
export default function AccountAddScreen() {
  const create = useCreateAccount();
  const [name, setName] = useState('');
  const [sourceApp, setSourceApp] = useState('手工账户');
  const [problem, setProblem] = useState<string | null>(null);

  function submit() {
    setProblem(null);
    if (!name.trim()) {
      setProblem('请输入账户名称');
      return;
    }
    create.mutate(
      { name: name.trim(), source_app: sourceApp, account_type: 'manual', import_mode: 'manual' },
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
        <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 6 }}>来源标签</Text>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginBottom: 12 }}>
          {SOURCE_LABELS.map((label) => (
            <Chip key={label} label={label} active={sourceApp === label} onPress={() => setSourceApp(label)} />
          ))}
        </View>
        <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
          来源标签只用于区分数据来自哪个应用，系统不会连接或保存任何第三方账号凭据。
        </Text>
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
        <Button label="创建账户" onPress={submit} loading={create.isPending} />
      </Card>
    </Screen>
  );
}
