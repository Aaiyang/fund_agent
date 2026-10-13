import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { FundQueryField } from '@/components/FundQueryField';
import { theme } from '@/constants/theme';
import { useCreateManualImport, type ManualPosition } from '@/hooks/useImports';
import { useAccounts } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';

type DraftRow = { query: string; code: string | null; name: string | null; market_value: string; profit_loss: string };

const EMPTY_ROW: DraftRow = { query: '', code: null, name: null, market_value: '', profit_loss: '' };

/** 手动批量录入：先解析成草稿，再跳到审阅页逐条确认。 */
export default function ManualImportScreen() {
  const accounts = useAccounts();
  const create = useCreateManualImport();
  const viewAccount = useUiStore((state) => state.accountId);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [rows, setRows] = useState<DraftRow[]>([EMPTY_ROW]);
  const [problem, setProblem] = useState<string | null>(null);
  // 顶部导航选中的账户就是导入目标；这里另选的账户只改写本表单，
  // 而“全部账户”视图本身不是合法的导入目标。
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
      setProblem('请至少填写一条持仓的基金代码或名称');
      return;
    }
    // 只在真的填了内容时校验：留空是“这行没有这个数字”，不是格式错误。
    const badField = filled.find((row) => isNotNumber(row.market_value) || isNotNumber(row.profit_loss));
    if (badField) {
      setProblem('当前持有金额与持有收益需为数字');
      return;
    }
    const positions: ManualPosition[] = filled.map((row) => {
      const query = row.query.trim();
      // 从联想建议里选中的项自带精确代码；纯手输则按形态分流，
      // 保证后端解析器拿到的要么是代码要么是名称。
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
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
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
    </KeyboardAvoidingView>
  );
}

function toNumber(value: string): number | null {
  return value.trim() === '' ? null : Number(value);
}

/** 填了但不是一个数：与其让 NaN 到后端换个看不懂的 422，不如当场说清。 */
function isNotNumber(value: string): boolean {
  return value.trim() !== '' && Number.isNaN(Number(value));
}
