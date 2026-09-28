import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { PurchaseDateFields, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Row, Screen, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAccounts, usePosition, useRecordTrade, useTradePreview, type PositionItem } from '@/hooks/usePortfolio';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useUiStore } from '@/stores/ui';
import { formatMoney, formatNumber, formatSignedMoney, localToday } from '@/utils/format';

/**
 * 加减仓: record one order and let the ledger re-project the holding.
 *
 * This is the path where a date prices something — an order placed before 15:00
 * buys at that day's NAV, later ones at the next session's — which is why the
 * confirm day and its NAV are shown next to the inputs rather than assumed.
 */
export default function TradeScreen() {
  const params = useLocalSearchParams<{ code?: string; account_id?: string; direction?: string }>();
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

  return (
    <TradeForm
      accounts={accounts.data?.items ?? []}
      accountId={accountId}
      onSelectAccount={setSelectedAccount}
      fundCode={fundCode}
      existing={existing.data ?? null}
      initialDirection={params.direction === 'SELL' ? 'SELL' : 'BUY'}
    />
  );
}

function TradeForm({
  accounts,
  accountId,
  onSelectAccount,
  fundCode,
  existing,
  initialDirection,
}: {
  accounts: { id: number; name: string }[];
  accountId: number | null;
  onSelectAccount: (accountId: number) => void;
  fundCode: string;
  existing: PositionItem | null;
  initialDirection: 'BUY' | 'SELL';
}) {
  const record = useRecordTrade();
  const [direction, setDirection] = useState<'BUY' | 'SELL'>(initialDirection);
  const [amount, setAmount] = useState('');
  const [shares, setShares] = useState('');
  const [fee, setFee] = useState('');
  const [tradeDate, setTradeDate] = useState(localToday());
  const [afterCutoff, setAfterCutoff] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const settledAmount = useDebouncedValue(amount);
  const settledShares = useDebouncedValue(shares);
  const settledFee = useDebouncedValue(fee);
  const settledDate = useDebouncedValue(tradeDate);
  const preview = useTradePreview({
    accountId,
    fundCode: fundCode.trim(),
    direction,
    tradeDate: settledDate.trim(),
    afterCutoff,
    amount: settledAmount.trim(),
    shares: settledShares.trim(),
    fee: settledFee.trim(),
  });

  const held = existing?.shares ?? 0;
  const sized = direction === 'BUY' ? amount.trim() !== '' : shares.trim() !== '';

  function submit() {
    setProblem(null);
    if (accountId === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    const dateProblem = purchaseDateProblem(tradeDate);
    if (dateProblem) {
      setProblem(dateProblem);
      return;
    }
    const value = direction === 'BUY' ? amount : shares;
    if (value.trim() === '' || Number.isNaN(Number(value)) || Number(value) <= 0) {
      setProblem(direction === 'BUY' ? '请填写买入金额' : '请填写卖出份额');
      return;
    }
    record.mutate(
      {
        fundCode: fundCode.trim(),
        account_id: accountId,
        direction,
        trade_date: tradeDate.trim(),
        after_cutoff: afterCutoff,
        amount: direction === 'BUY' ? Number(amount) : null,
        shares: direction === 'SELL' ? Number(shares) : null,
        fee: fee.trim() === '' ? null : Number(fee),
      },
      {
        onSuccess: () => router.back(),
        onError: (error) =>
          setProblem(
            error instanceof ApiError && error.status === 409
              ? '这一天的净值还没有公布，等净值同步之后再记这一单'
              : error instanceof ApiError && error.message.includes('shares_exceed_holding')
                ? `卖出份额不能超过当前持仓 ${formatNumber(held, 2)} 份`
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
        </View>
      </Card>

      <Card>
        <SectionTitle title={`加减仓 · ${fundCode}`} />
        <View style={{ flexDirection: 'row', marginBottom: 12 }}>
          <Chip label="买入" active={direction === 'BUY'} onPress={() => setDirection('BUY')} />
          <Chip label="卖出" active={direction === 'SELL'} onPress={() => setDirection('SELL')} />
        </View>
        <PurchaseDateFields
          value={tradeDate}
          onChangeText={setTradeDate}
          afterCutoff={afterCutoff}
          onAfterCutoff={setAfterCutoff}
        />
        {direction === 'BUY' ? (
          <Field
            label="买入金额"
            value={amount}
            onChangeText={setAmount}
            keyboardType="numeric"
            placeholder="请输入本次买入金额"
          />
        ) : (
          <Field
            label="卖出份额"
            value={shares}
            onChangeText={setShares}
            keyboardType="numeric"
            placeholder={`当前持有 ${formatNumber(held, 2)} 份`}
          />
        )}
        <Field
          label="手续费（可选）"
          value={fee}
          onChangeText={setFee}
          keyboardType="numeric"
          placeholder="申购费/赎回费，买入时不计入份额"
        />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13 }}>{problem}</Text> : null}
      </Card>

      {sized ? <Preview query={preview} direction={direction} /> : null}

      <Card>
        <Button
          label={direction === 'BUY' ? '确认买入' : '确认卖出'}
          onPress={submit}
          loading={record.isPending}
        />
      </Card>
    </Screen>
  );
}

type PreviewQuery = ReturnType<typeof useTradePreview>;

function Preview({ query, direction }: { query: PreviewQuery; direction: 'BUY' | 'SELL' }) {
  if (query.isFetching && !query.data) {
    return (
      <Card>
        <SectionTitle title="成交预览" />
        <Text style={{ fontSize: 13, color: theme.textMuted }}>按确认日净值计算中…</Text>
      </Card>
    );
  }
  const data = query.data;
  if (!data) {
    return null;
  }
  const carried = data.cost_after && data.shares_after ? data.cost_after / data.shares_after : null;
  // A sell's gain is what arrived minus the cost that left with it; the ledger
  // carries cost out at the average, so the difference is this order's result.
  const realized = data.order_amount - (data.cost_before - data.cost_after);
  return (
    <Card>
      <SectionTitle title="成交预览" />
      <Row>
        <Stat label={`确认日 ${data.confirm_date}`} value={formatNumber(data.confirm_nav, 4)} tone="muted" />
        <Stat
          label={direction === 'BUY' ? '得到份额' : '卖出份额'}
          value={formatNumber(data.order_shares, 2)}
          tone="muted"
        />
        <Stat label={direction === 'BUY' ? '付款金额' : '到账金额'} value={formatMoney(data.order_amount)} />
        <Stat label="成交后份额" value={formatNumber(data.shares_after, 2)} tone="muted" />
        <Stat label="成交后成本" value={formatMoney(data.cost_after)} tone="muted" />
        <Stat label="成本净值" value={formatNumber(carried, 4)} tone="muted" />
        {direction === 'SELL' ? (
          <Stat label="本单盈亏" value={formatSignedMoney(realized)} tone={realized > 0 ? 'up' : 'down'} />
        ) : null}
      </Row>
      <Text style={{ fontSize: 12, color: theme.textFaint }}>
        {data.confirm_date !== data.confirm_nav_date
          ? `${data.confirm_date} 当天没有净值，按最近一场 ${data.confirm_nav_date} 的净值算。`
          : '份额与成本由流水累计得出，卖出按持仓均价结转成本。'}
      </Text>
    </Card>
  );
}
