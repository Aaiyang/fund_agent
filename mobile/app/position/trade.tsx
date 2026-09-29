import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { FundReference } from '@/components/FundReference';
import { PurchaseDateFields, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Row, Screen, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useFundDetail } from '@/hooks/useFunds';
import { useAccounts, usePosition, useRecordTrade, useTradePreview, type PositionItem, type TradeOperation } from '@/hooks/usePortfolio';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useUiStore } from '@/stores/ui';
import { formatMoney, formatNumber, formatSignedMoney, localToday } from '@/utils/format';

const OPERATIONS: {
  key: TradeOperation;
  label: string;
  verb: string;
  byMoney: boolean;
  pickDate: boolean;
  amountLabel: string;
}[] = [
  { key: 'BUY', label: '加仓', verb: '确认加仓', byMoney: true, pickDate: true, amountLabel: '买入金额' },
  { key: 'SELL', label: '减仓', verb: '确认减仓', byMoney: false, pickDate: true, amountLabel: '' },
  { key: 'AUTO_INVEST', label: '定投', verb: '确认定投', byMoney: true, pickDate: false, amountLabel: '本期定投金额' },
  { key: 'CONVERT', label: '转换', verb: '确认转换', byMoney: false, pickDate: true, amountLabel: '' },
];

/**
 * 加减仓: record one order against the holding he already has. Which operation
 * this is comes from the button that opened the screen — re-asking here only
 * let him change his mind after typing. 定投 fixes its own day to today and
 * prices before the cutoff, so it asks for an amount and nothing else.
 */
export default function TradeScreen() {
  const params = useLocalSearchParams<{ code?: string; account_id?: string; operation?: string }>();
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
  const operation: TradeOperation = OPERATIONS.some((entry) => entry.key === params.operation)
    ? (params.operation as TradeOperation)
    : 'BUY';

  if (accounts.isPending || (accountId !== null && fundCode.length === 6 && existing.isPending)) {
    return (
      <Screen>
        <LoadingState />
      </Screen>
    );
  }

  return (
    <TradeForm
      accounts={accounts.data?.items ?? []}
      accountId={accountId}
      onSelectAccount={setSelectedAccount}
      fundCode={fundCode}
      existing={existing.data ?? null}
      operation={operation}
    />
  );
}

function TradeForm({
  accounts,
  accountId,
  onSelectAccount,
  fundCode,
  existing,
  operation,
}: {
  accounts: { id: number; name: string }[];
  accountId: number | null;
  onSelectAccount: (accountId: number) => void;
  fundCode: string;
  existing: PositionItem | null;
  operation: TradeOperation;
}) {
  const record = useRecordTrade();
  const detail = useFundDetail(fundCode.length === 6 ? fundCode : null);
  const entry = OPERATIONS.find((item) => item.key === operation) ?? OPERATIONS[0];
  const [amount, setAmount] = useState('');
  const [shares, setShares] = useState('');
  const [targetCode, setTargetCode] = useState('');
  const [tradeDate, setTradeDate] = useState(localToday());
  const [afterCutoff, setAfterCutoff] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const settledAmount = useDebouncedValue(amount);
  const settledShares = useDebouncedValue(shares);
  const settledDate = useDebouncedValue(tradeDate);
  const settledTarget = useDebouncedValue(targetCode);
  const preview = useTradePreview({
    accountId,
    fundCode: fundCode.trim(),
    operation,
    tradeDate: settledDate.trim(),
    afterCutoff,
    amount: settledAmount.trim(),
    shares: settledShares.trim(),
    targetCode: settledTarget.trim(),
  });

  const held = existing?.shares ?? 0;
  const sized = entry.byMoney ? amount.trim() !== '' : shares.trim() !== '';

  function submit() {
    setProblem(null);
    if (accountId === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    const dateProblem = purchaseDateProblem(tradeDate, true);
    if (dateProblem) {
      setProblem(dateProblem);
      return;
    }
    const value = entry.byMoney ? amount : shares;
    if (value.trim() === '' || Number.isNaN(Number(value)) || Number(value) <= 0) {
      setProblem(entry.byMoney ? '请填写金额' : '请填写份额');
      return;
    }
    if (operation === 'CONVERT' && !/^\d{6}$/.test(targetCode.trim())) {
      setProblem('请填写转入基金的 6 位代码');
      return;
    }
    record.mutate(
      {
        fundCode: fundCode.trim(),
        account_id: accountId,
        operation,
        trade_date: entry.pickDate ? tradeDate.trim() : localToday(),
        after_cutoff: entry.pickDate ? afterCutoff : false,
        amount: entry.byMoney ? Number(amount) : null,
        shares: entry.byMoney ? null : Number(shares),
        target_code: operation === 'CONVERT' ? targetCode.trim() : null,
      },
      {
        onSuccess: () => router.back(),
        onError: (error) => setProblem(describeTradeError(error, held)),
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
        </View>
      </Card>

      <Card>
        <SectionTitle title="加减仓" />
        <FundReference
          code={fundCode}
          name={detail.data?.fund_name ?? existing?.fund_name}
          nav={detail.data?.latest_nav ?? existing?.unit_nav}
          navDate={detail.data?.nav_date ?? existing?.nav_date}
          dailyReturn={detail.data?.daily_return ?? existing?.daily_return}
          note={`当前持有 ${formatNumber(held, 2)} 份 · 市值 ${formatMoney(existing?.market_value)}`}
        />
        <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 12 }}>{entry.label}</Text>
        {entry.pickDate ? (
          <PurchaseDateFields
            required
            value={tradeDate}
            onChangeText={setTradeDate}
            afterCutoff={afterCutoff}
            onAfterCutoff={setAfterCutoff}
          />
        ) : (
          <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 12 }}>
            本期扣款日 {tradeDate}，按 15:00 前的净值计算。
          </Text>
        )}
        {entry.byMoney ? (
          <Field
            label={entry.amountLabel}
            value={amount}
            onChangeText={setAmount}
            keyboardType="numeric"
            placeholder="请输入金额"
          />
        ) : (
          <Field
            label="转出份额"
            value={shares}
            onChangeText={setShares}
            keyboardType="numeric"
            placeholder={`当前持有 ${formatNumber(held, 2)} 份`}
          />
        )}
        {operation === 'CONVERT' ? (
          <Field
            label="转入基金代码"
            value={targetCode}
            onChangeText={setTargetCode}
            keyboardType="numeric"
            placeholder="请输入转入基金的 6 位代码"
          />
        ) : null}
        {problem ? <Text style={{ color: theme.danger, fontSize: 13 }}>{problem}</Text> : null}
      </Card>

      {sized ? <Preview query={preview} byMoney={entry.byMoney} /> : null}

      <Card>
        <Button label={entry.verb} onPress={submit} loading={record.isPending} />
      </Card>
    </Screen>
  );
}

function describeTradeError(error: unknown, held: number): string {
  if (error instanceof ApiError) {
    if (error.status === 409) return '这一天的净值还没有公布，等净值同步之后再记这一单';
    if (error.message.includes('shares_exceed_holding')) {
      return `转出份额不能超过当前持仓 ${formatNumber(held, 2)} 份`;
    }
  }
  return describeError(error);
}

type PreviewQuery = ReturnType<typeof useTradePreview>;

/** One card per fund the order moves money through — two for a conversion. */
function Preview({ query, byMoney }: { query: PreviewQuery; byMoney: boolean }) {
  if (query.isFetching && !query.data) {
    return (
      <Card>
        <SectionTitle title="成交预览" />
        <Text style={{ fontSize: 13, color: theme.textMuted }}>按确认日净值计算中…</Text>
      </Card>
    );
  }
  const data = query.data;
  if (!data) return null;
  return (
    <>
      {data.legs.map((leg) => {
        const carried = leg.cost_after && leg.shares_after ? leg.cost_after / leg.shares_after : null;
        // What arrived minus the cost that left with it: the ledger carries
        // cost out at the average, so this difference is this order's result.
        const realized = leg.direction === 'SELL' ? leg.amount - (leg.cost_before - leg.cost_after) : null;
        return (
          <Card key={`${leg.fund_code}-${leg.direction}`}>
            <SectionTitle title={`${leg.fund_code} ${leg.direction === 'SELL' ? '转出' : '转入'}`} />
            <Row>
              <Stat label={`确认日 ${data.confirm_date}`} value={formatNumber(leg.confirm_nav, 4)} tone="muted" />
              <Stat
                label={byMoney ? '得到份额' : '份额变动'}
                value={formatSignedNumber(leg.shares_delta)}
                tone="muted"
              />
              <Stat label={leg.direction === 'SELL' ? '到账金额' : '投入金额'} value={formatMoney(leg.amount)} />
              <Stat label="成交后份额" value={formatNumber(leg.shares_after, 2)} tone="muted" />
              <Stat label="成交后成本" value={formatMoney(leg.cost_after)} tone="muted" />
              <Stat label="成本净值" value={formatNumber(carried, 4)} tone="muted" />
              {realized !== null ? (
                <Stat label="本单盈亏" value={formatSignedMoney(realized)} tone={realized > 0 ? 'up' : 'down'} />
              ) : null}
            </Row>
            {leg.confirm_nav_date !== data.confirm_date ? (
              <Text style={{ fontSize: 12, color: theme.textFaint }}>
                {data.confirm_date} 当天没有净值，按最近一场 {leg.confirm_nav_date} 的净值算。
              </Text>
            ) : null}
          </Card>
        );
      })}
    </>
  );
}

function formatSignedNumber(value: number): string {
  return `${value > 0 ? '+' : ''}${formatNumber(value, 2)}`;
}
