import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAccounts, usePosition, useUpsertPosition, type PositionItem } from '@/hooks/usePortfolio';
import { formatDateTime, formatMoney, toInputNumber } from '@/utils/format';
import { useUiStore } from '@/stores/ui';

/** Create or edit one holding snapshot (spec 3.7.1, optimistic lock 7.11). */
export default function PositionEditScreen() {
  const params = useLocalSearchParams<{ code?: string; account_id?: string }>();
  const viewAccount = useUiStore((state) => state.accountId);
  const accounts = useAccounts();
  const fundCode = params.code ?? '';
  const [selectedAccount, setSelectedAccount] = useState<number | null>(null);

  const accountId =
    selectedAccount ??
    (params.account_id && Number(params.account_id) > 0 ? Number(params.account_id) : null) ??
    viewAccount ??
    accounts.data?.items[0]?.id ??
    null;
  const existing = usePosition(accountId, fundCode.length === 6 ? fundCode : null);

  if (accounts.isPending || (accountId !== null && fundCode.length === 6 && existing.isPending)) {
    return (
      <Screen>
        <LoadingState />
      </Screen>
    );
  }

  // Remounting when the account or stored version changes re-seeds the form,
  // which is why no effect has to copy query data into field state.
  return (
    <PositionForm
      key={`${accountId}-${existing.data?.version ?? 'new'}`}
      accounts={accounts.data?.items ?? []}
      accountId={accountId}
      onSelectAccount={setSelectedAccount}
      initialCode={fundCode}
      existing={existing.data ?? null}
    />
  );
}

function PositionForm({
  accounts,
  accountId,
  onSelectAccount,
  initialCode,
  existing,
}: {
  accounts: { id: number; name: string }[];
  accountId: number | null;
  onSelectAccount: (accountId: number) => void;
  initialCode: string;
  existing: PositionItem | null;
}) {
  const upsert = useUpsertPosition();
  const [fundCode, setFundCode] = useState(initialCode);
  const [marketValue, setMarketValue] = useState(toInputNumber(existing?.market_value));
  const [shares, setShares] = useState(toInputNumber(existing?.shares));
  const [costAmount, setCostAmount] = useState(toInputNumber(existing?.cost_amount));
  // 净值 is published to four decimals; rounding further would change the number.
  const [averageCostNav, setAverageCostNav] = useState(toInputNumber(existing?.average_cost_nav, 4));
  const [profitLoss, setProfitLoss] = useState(toInputNumber(existing?.profit_loss));
  const [purchaseDate, setPurchaseDate] = useState(initialPurchaseDate(existing));
  // A row that never recorded a purchase keeps the import default: before the cutoff.
  const [afterCutoff, setAfterCutoff] = useState(Boolean(existing?.purchase_date && existing.purchase_after_cutoff));
  const [problem, setProblem] = useState<string | null>(null);

  function submit() {
    setProblem(null);
    if (accountId === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    if (!/^\d{6}$/.test(fundCode.trim())) {
      setProblem('基金代码需要是 6 位数字');
      return;
    }
    const fields: [string, string][] = [
      ['持有金额', marketValue],
      ['持有份额', shares],
      ['持仓成本', costAmount],
      ['平均成本净值', averageCostNav],
      ['持有收益', profitLoss],
    ];
    for (const [label, value] of fields) {
      if (value !== '' && Number.isNaN(Number(value))) {
        setProblem(`${label} 不是有效数字`);
        return;
      }
    }
    if (!isBlankDate(purchaseDate) && !isRealDate(purchaseDate)) {
      setProblem('买入确认日期格式应为 YYYY-MM-DD');
      return;
    }
    upsert.mutate(
      {
        fundCode: fundCode.trim(),
        account_id: accountId,
        market_value: number(marketValue),
        shares: number(shares),
        cost_amount: number(costAmount),
        average_cost_nav: number(averageCostNav),
        profit_loss: number(profitLoss),
        purchase_date: purchaseDate.trim() || null,
        purchase_after_cutoff: afterCutoff,
        // The lock token only matters for a row that already exists (spec 7.11).
        expected_version: existing?.version ?? null,
      },
      {
        onSuccess: () => router.back(),
        onError: (error) =>
          setProblem(
            error instanceof ApiError && error.status === 409
              ? '该持仓已被其他操作（例如截图导入）更新，请返回刷新后重试'
              : describeError(error),
          ),
      },
    );
  }

  return (
    <Screen>
      <Card>
        <SectionTitle title="持仓账户" />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {accounts.map((account) => (
            <Chip
              key={account.id}
              label={account.name}
              active={accountId === account.id}
              onPress={() => onSelectAccount(account.id)}
            />
          ))}
          <Chip label="+ 新增账户" onPress={() => router.push('/account/add')} />
        </View>
      </Card>

      <Card>
        <SectionTitle title="持仓快照" />
        <Field label="基金代码" value={fundCode} onChangeText={setFundCode} keyboardType="numeric" placeholder="请输入基金代码" />
        <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 10 }}>
          {existing
            ? `已存在持仓：市值 ${formatMoney(existing.market_value)}`
            : '该账户下还没有这只基金的持仓'}
        </Text>
        <Field label="买入确认日期" value={purchaseDate} onChangeText={setPurchaseDate} placeholder="请输入买入确认日期（YYYY-MM-DD）" />
        <View style={{ flexDirection: 'row', marginBottom: 12 }}>
          <Chip label="15:00前，按当日净值" active={!afterCutoff} onPress={() => setAfterCutoff(false)} />
          <Chip label="15:00后，按次日净值" active={afterCutoff} onPress={() => setAfterCutoff(true)} />
        </View>
        <Field label="持有金额" value={marketValue} onChangeText={setMarketValue} keyboardType="numeric" placeholder="请输入当前持有金额" />
        <Field label="持有份额" value={shares} onChangeText={setShares} keyboardType="numeric" placeholder="请输入持有份额" />
        <Field label="持仓成本" value={costAmount} onChangeText={setCostAmount} keyboardType="numeric" placeholder="请输入持仓成本" />
        <Field
          label="平均成本净值"
          value={averageCostNav}
          onChangeText={setAverageCostNav}
          keyboardType="numeric"
          placeholder="请输入平均成本净值"
        />
        <Field label="持有收益" value={profitLoss} onChangeText={setProfitLoss} keyboardType="numeric" placeholder="请输入持有收益" />
        <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
          只填你确定知道的字段：留空的字段保持原值，系统不会推算缺失数据。
        </Text>
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
        <Button label="保存持仓" onPress={submit} loading={upsert.isPending} />
      </Card>
    </Screen>
  );
}

function number(value: string): number | null {
  return value.trim() === '' ? null : Number(value);
}

/** The stored date, else the day the snapshot was taken — an imported holding
 * has no trade date of its own — else today on the device. */
function initialPurchaseDate(existing: PositionItem | null): string {
  if (existing?.purchase_date) return existing.purchase_date;
  const stamp = existing?.created_at ?? existing?.updated_at;
  return stamp ? formatDateTime(stamp).slice(0, 10) : localToday();
}

function localToday(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function isBlankDate(value: string): boolean {
  return value.trim() === '';
}

function isRealDate(value: string): boolean {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!parts) return false;
  const [year, month, day] = parts.slice(1).map(Number);
  // UTC math keeps a device west of Greenwich from rejecting its own dates.
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() + 1 === month && parsed.getUTCDate() === day;
}
