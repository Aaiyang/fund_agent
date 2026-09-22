import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useCreateManualImport, type ManualPosition } from '@/hooks/useImports';
import { useAccounts } from '@/hooks/usePortfolio';

type DraftRow = { fund_code: string; fund_name: string; market_value: string; shares: string; profit_loss: string };

const EMPTY_ROW: DraftRow = { fund_code: '', fund_name: '', market_value: '', shares: '', profit_loss: '' };

/** Manual batch entry: parsed into a draft, confirmed on the review page. */
export default function ManualImportScreen() {
  const accounts = useAccounts();
  const create = useCreateManualImport();
  const [accountId, setAccountId] = useState<number | null>(null);
  const [sourceApp, setSourceApp] = useState('');
  const [rows, setRows] = useState<DraftRow[]>([EMPTY_ROW]);
  const [problem, setProblem] = useState<string | null>(null);
  const chosen = accountId ?? accounts.data?.items[0]?.id ?? null;

  function updateRow(index: number, patch: Partial<DraftRow>) {
    setRows((current) => current.map((row, position) => (position === index ? { ...row, ...patch } : row)));
  }

  function submit() {
    setProblem(null);
    if (chosen === null) {
      setProblem('请先创建一个持仓账户');
      return;
    }
    const filled = rows.filter((row) => row.fund_code.trim() || row.fund_name.trim());
    if (filled.length === 0) {
      setProblem('至少填写一条持仓（基金代码或名称）');
      return;
    }
    const positions: ManualPosition[] = filled.map((row) => ({
      fund_code: row.fund_code.trim() || null,
      fund_name: row.fund_name.trim() || null,
      market_value: toNumber(row.market_value),
      shares: toNumber(row.shares),
      profit_loss: toNumber(row.profit_loss),
    }));
    create.mutate(
      { account_id: chosen, source_app: sourceApp.trim() || null, positions },
      {
        onSuccess: (detail) => router.replace(`/holding-import/${detail.id}`),
        onError: (error) => setProblem(describeError(error)),
      },
    );
  }

  return (
    <Screen>
      <Card>
        <SectionTitle title="导入到账户" />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {(accounts.data?.items ?? []).map((account) => (
            <Chip
              key={account.id}
              label={account.name}
              active={chosen === account.id}
              onPress={() => setAccountId(account.id)}
            />
          ))}
          <Chip label="+ 新增账户" onPress={() => router.push('/account/add')} />
        </View>
        <Field label="来源应用标签（可选）" value={sourceApp} onChangeText={setSourceApp} placeholder="支付宝 / 天天基金 / 手工" />
      </Card>

      {rows.map((row, index) => (
        <Card key={index}>
          <SectionTitle
            title={`第 ${index + 1} 条`}
            action={rows.length > 1 ? '移除' : undefined}
            onAction={rows.length > 1 ? () => setRows((current) => current.filter((_, position) => position !== index)) : undefined}
          />
          <Field label="基金代码（6 位）" value={row.fund_code} onChangeText={(value) => updateRow(index, { fund_code: value })} keyboardType="numeric" placeholder="011452" />
          <Field label="或基金名称" value={row.fund_name} onChangeText={(value) => updateRow(index, { fund_name: value })} placeholder="华泰柏瑞质量成长混合C" />
          <Field label="持有金额" value={row.market_value} onChangeText={(value) => updateRow(index, { market_value: value })} keyboardType="numeric" placeholder="881.99" />
          <Field label="持有份额（可选）" value={row.shares} onChangeText={(value) => updateRow(index, { shares: value })} keyboardType="numeric" placeholder="295.1" />
          <Field label="持有收益（可选）" value={row.profit_loss} onChangeText={(value) => updateRow(index, { profit_loss: value })} keyboardType="numeric" placeholder="-137.20" />
        </Card>
      ))}

      <Card>
        <Button label="+ 再加一条" variant="secondary" onPress={() => setRows((current) => [...current, EMPTY_ROW])} />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginTop: 12 }}>{problem}</Text> : null}
        <View style={{ marginTop: 10 }}>
          <Button label="生成待确认草稿" onPress={submit} loading={create.isPending} />
        </View>
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 8 }}>
          草稿不会改动正式持仓，下一步可逐条核对并确认。
        </Text>
      </Card>
    </Screen>
  );
}

function toNumber(value: string): number | null {
  return value.trim() === '' ? null : Number(value);
}
