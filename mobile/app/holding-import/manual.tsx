import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { FundQueryField } from '@/components/FundQueryField';
import { theme } from '@/constants/theme';
import { useCreateManualImport, type ManualPosition } from '@/hooks/useImports';
import { useAccounts } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';

type DraftRow = { query: string; code: string | null; name: string | null; market_value: string; profit_loss: string };

const EMPTY_ROW: DraftRow = { query: '', code: null, name: null, market_value: '', profit_loss: '' };

/** Manual batch entry: parsed into a draft, confirmed on the review page. */
export default function ManualImportScreen() {
  const accounts = useAccounts();
  const create = useCreateManualImport();
  const viewAccount = useUiStore((state) => state.accountId);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [rows, setRows] = useState<DraftRow[]>([EMPTY_ROW]);
  const [problem, setProblem] = useState<string | null>(null);
  // The account selected in the top nav is the import target; a pick made here
  // only rewrites this form, and 全部账户 has no target of its own.
  const chosen = accountId ?? viewAccount ?? accounts.data?.items[0]?.id ?? null;

  function updateRow(index: number, patch: Partial<DraftRow>) {
    setRows((current) => current.map((row, position) => (position === index ? { ...row, ...patch } : row)));
  }

  function submit() {
    setProblem(null);
    if (chosen === null) {
      setProblem('请先创建一个持仓账户');
      return;
    }
    const filled = rows.filter((row) => row.query.trim());
    if (filled.length === 0) {
      setProblem('至少填写一条持仓（基金代码或名称）');
      return;
    }
    const positions: ManualPosition[] = filled.map((row) => {
      const query = row.query.trim();
      // A picked suggestion carries the exact code; free text is routed by
      // shape so the backend resolver gets it as code or as name.
      const digits = /^\d{6}$/.test(query);
      return {
        fund_code: row.code ?? (digits ? query : null),
        fund_name: row.name ?? (digits ? null : query),
        market_value: toNumber(row.market_value),
        profit_loss: toNumber(row.profit_loss),
      };
    });
    create.mutate(
      { account_id: chosen, positions },
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
      </Card>

      {rows.map((row, index) => (
        <Card key={index}>
          <SectionTitle
            title={`第 ${index + 1} 条`}
            action={rows.length > 1 ? '移除' : undefined}
            onAction={
              rows.length > 1
                ? () => setRows((current) => current.filter((_, position) => position !== index))
                : undefined
            }
          />
          <FundQueryField
            label="基金（代码或名称）"
            value={row.query}
            matchedCode={row.code}
            onChangeText={(text) => updateRow(index, { query: text, code: null, name: null })}
            onPick={(fund) => updateRow(index, { query: fund.name, code: fund.code, name: fund.name })}
          />
          <Field label="当前持有金额" value={row.market_value} onChangeText={(value) => updateRow(index, { market_value: value })} keyboardType="numeric" placeholder="请输入当前持有金额" />
          <Field label="持有收益" value={row.profit_loss} onChangeText={(value) => updateRow(index, { profit_loss: value })} keyboardType="numeric" placeholder="请输入持有收益" />
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
