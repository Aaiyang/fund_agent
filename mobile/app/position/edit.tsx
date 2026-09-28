import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { PurchaseDateFields, initialPurchaseDate, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Row, Screen, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAccounts, usePosition, usePositionPreview, useUpsertPosition, type PositionItem } from '@/hooks/usePortfolio';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useUiStore } from '@/stores/ui';
import { formatMoney, formatNumber, formatSignedMoney, formatSignedRate, toInputNumber } from '@/utils/format';

/**
 * Create or edit one holding snapshot (spec 3.7.1, optimistic lock 7.11).
 *
 * Only what a person actually knows is entered: which fund, how much it is
 * worth now, and when it was bought. 份额/成本/收益 follow from the NAV the
 * purchase settled on, so they are shown as an estimate rather than asked for
 * — a hand-typed guess would otherwise be stored as fact and never revisited.
 */
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
  const [purchaseDate, setPurchaseDate] = useState(
    initialPurchaseDate(existing?.purchase_date, existing?.created_at ?? existing?.updated_at),
  );
  // A row that never recorded a purchase keeps the import default: before the cutoff.
  const [afterCutoff, setAfterCutoff] = useState(Boolean(existing?.purchase_date && existing.purchase_after_cutoff));
  // The stored columns, not the figures the list shows: a derived cost must not
  // come back as if it had been typed in.
  const storedCost = existing && !existing.cost_derived ? toInputNumber(existing.cost_amount) : '';
  const storedProfit = existing && !existing.profit_derived ? toInputNumber(existing.profit_loss) : '';
  const [manualOpen, setManualOpen] = useState(Boolean(storedCost || storedProfit));
  const [manualCost, setManualCost] = useState(storedCost);
  const [manualProfit, setManualProfit] = useState(storedProfit);
  const [problem, setProblem] = useState<string | null>(null);

  const settledAmount = useDebouncedValue(marketValue);
  const settledDate = useDebouncedValue(purchaseDate);
  const preview = usePositionPreview({
    fundCode: fundCode.trim(),
    purchaseDate: settledDate.trim(),
    afterCutoff,
    marketValue: settledAmount.trim(),
  });

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
    const amounts: [string, string][] = manualOpen
      ? [
          ['持有金额', marketValue],
          ['持仓成本', manualCost],
          ['持有收益', manualProfit],
        ]
      : [['持有金额', marketValue]];
    for (const [label, value] of amounts) {
      if (value.trim() !== '' && Number.isNaN(Number(value))) {
        setProblem(`${label} 不是有效数字`);
        return;
      }
    }
    const dateProblem = purchaseDateProblem(purchaseDate);
    if (dateProblem) {
      setProblem(dateProblem);
      return;
    }
    // While the section is open its fields own those columns: blanking one puts
    // the figure back on the derived path. Closed, they are left untouched.
    const reset = manualOpen
      ? [
          ...(manualCost.trim() === '' && storedCost !== '' ? ['cost_amount' as const] : []),
          ...(manualProfit.trim() === '' && storedProfit !== '' ? ['profit_loss' as const] : []),
        ]
      : [];
    upsert.mutate(
      {
        fundCode: fundCode.trim(),
        account_id: accountId,
        market_value: number(marketValue),
        cost_amount: manualOpen ? number(manualCost) : null,
        profit_loss: manualOpen ? number(manualProfit) : null,
        purchase_date: purchaseDate.trim() || null,
        purchase_after_cutoff: afterCutoff,
        reset,
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
        <SectionTitle title="买入信息" />
        <Field
          label="基金代码"
          value={fundCode}
          onChangeText={setFundCode}
          keyboardType="numeric"
          placeholder="请输入基金代码"
        />
        <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 10 }}>
          {existing ? `已存在持仓：市值 ${formatMoney(existing.market_value)}` : '该账户下还没有这只基金的持仓'}
        </Text>
        <PurchaseDateFields
          value={purchaseDate}
          onChangeText={setPurchaseDate}
          afterCutoff={afterCutoff}
          onAfterCutoff={setAfterCutoff}
        />
        <Field
          label="持有金额"
          value={marketValue}
          onChangeText={setMarketValue}
          keyboardType="numeric"
          placeholder="请输入当前持有金额"
        />
        {manualOpen ? (
          <>
            <Field
              label="持仓成本"
              value={manualCost}
              onChangeText={setManualCost}
              keyboardType="numeric"
              placeholder="留空则按系统推算"
            />
            <Field
              label="持有收益"
              value={manualProfit}
              onChangeText={setManualProfit}
              keyboardType="numeric"
              placeholder="留空则按系统推算"
            />
            <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
              多笔买入时成本推不准，按你实际的总投入填；填了就以你填的为准，清空则改回系统推算。
            </Text>
          </>
        ) : null}
        <Chip
          label={manualOpen ? '收起手动修正' : '手动修正成本（多笔买入时）'}
          active={manualOpen}
          onPress={() => setManualOpen(!manualOpen)}
        />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginTop: 12 }}>{problem}</Text> : null}
      </Card>

      <DerivedCard preview={preview} settledDate={settledDate.trim()} amount={settledAmount.trim()} />

      <Card>
        <Button label="保存持仓" onPress={submit} loading={upsert.isPending} />
      </Card>
    </Screen>
  );
}

type Preview = ReturnType<typeof usePositionPreview>;

/** The estimate the save will be priced on, with the two NAVs it came from. */
function DerivedCard({ preview, settledDate, amount }: { preview: Preview; settledDate: string; amount: string }) {
  if (!settledDate) {
    return null;
  }
  // A disabled query reports `isPending` too, so only a live request is "推算中".
  if (preview.isPending && preview.isFetching) {
    return (
      <Card>
        <SectionTitle title="系统推算" />
        <Text style={{ fontSize: 13, color: theme.textMuted }}>推算中…</Text>
      </Card>
    );
  }
  const data = preview.data;
  if (!data) {
    return null;
  }
  const note = data.unit_nav
    ? data.settled_nav
      ? '成本 = 持有金额 × 确认日净值 ÷ 最新净值'
      : `还没有 ${settledDate} 之前的净值记录，成本推不出来`
    : '这只基金还没有净值记录';
  return (
    <Card>
      <SectionTitle title="系统推算" />
      <Row>
        <Stat label={`确认日净值 ${data.settled_nav_date ?? ''}`} value={formatNumber(data.settled_nav, 4)} tone="muted" />
        <Stat label={`最新净值 ${data.nav_date ?? ''}`} value={formatNumber(data.unit_nav, 4)} tone="muted" />
        <Stat label="持有份额" value={formatNumber(data.shares, 2)} tone="muted" />
        <Stat label="持仓成本" value={formatMoney(data.cost_amount)} />
        <Stat label="平均成本净值" value={formatNumber(data.average_cost_nav, 4)} tone="muted" />
        <Stat label="持有收益" value={formatSignedMoney(data.profit_loss)} tone={signTone(data.profit_loss)} />
        <Stat label="收益率" value={formatSignedRate(data.profit_loss_rate)} tone={signTone(data.profit_loss_rate)} />
        <Stat label="持有天数" value={`${data.holding_days ?? '--'}`} tone="muted" />
      </Row>
      <Text style={{ fontSize: 12, color: theme.textFaint }}>
        {amount.trim() === '' ? '填好持有金额就能算出成本与收益。' : note}
      </Text>
    </Card>
  );
}

function signTone(value: number | null | undefined): 'up' | 'down' | 'muted' {
  if (!value) return 'muted';
  return value > 0 ? 'up' : 'down';
}

function number(value: string): number | null {
  return value.trim() === '' ? null : Number(value);
}
