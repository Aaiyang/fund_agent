import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { PurchaseDateField, initialPurchaseDate, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Row, Screen, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useFundDetail } from '@/hooks/useFunds';
import { useAccounts, usePosition, useUpsertPosition, type PositionItem } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import { formatMoney, formatNumber, formatSignedMoney, formatSignedRate, isCalendarDate, toInputNumber } from '@/utils/format';

/**
 * 同步持仓: restate what a third-party holdings screen shows (spec 3.7.1).
 *
 * This is the snapshot path, not the trade path — no date prices anything here.
 * The three money figures are what he reads off the screen; the fourth is
 * implied by them, so the form works out whichever side he did not type and
 * shows it as a result rather than as another box.
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
  const code = initialCode.trim();
  const detail = useFundDetail(code.length === 6 ? code : null);
  const [fundCode, setFundCode] = useState(initialCode);
  const [purchaseDate, setPurchaseDate] = useState(
    initialPurchaseDate(existing?.purchase_date, existing?.created_at ?? existing?.updated_at),
  );
  // A ledger owns these columns, so the snapshot keeps only what it may still
  // correct: the value on screen and the day the holding started.
  const traded = tradedPosition(existing);
  const [mode, setMode] = useState<'amount' | 'shares'>('amount');
  const [marketValue, setMarketValue] = useState(snapshotText(existing, 'market_value'));
  const [shares, setShares] = useState(traded || existing?.shares_derived ? '' : toInputNumber(existing?.shares));
  const [costAmount, setCostAmount] = useState(snapshotText(existing, 'cost_amount'));
  const [profitLoss, setProfitLoss] = useState(snapshotText(existing, 'profit_loss'));
  const [problem, setProblem] = useState<string | null>(null);

  const nav = detail.data?.latest_nav ?? existing?.unit_nav ?? null;
  const days = daysSince(purchaseDate);
  const typed = resolve({ marketValue, shares, costAmount, profitLoss, nav, mode, traded });
  // With a ledger the figures he cannot edit are still the ones the trades add
  // up to, so the card reports those rather than blanks next to his one input.
  const result = traded
    ? {
        market_value: typed.market_value ?? existing?.market_value ?? null,
        shares: existing?.shares ?? null,
        cost_amount: existing?.cost_amount ?? null,
        profit_loss: existing?.profit_loss ?? null,
        average_cost_nav: existing?.average_cost_nav ?? null,
        profit_loss_rate: existing?.profit_loss_rate ?? null,
      }
    : typed;
  const figures = { ...result, holding_days: days };

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
    const dateProblem = purchaseDateProblem(purchaseDate);
    if (dateProblem) {
      setProblem(dateProblem);
      return;
    }
    const boxes: [keyof typeof LABELS, string][] = traded
      ? [['market_value', marketValue]]
      : mode === 'amount'
        ? [
            ['market_value', marketValue],
            ['cost_amount', costAmount],
            ['profit_loss', profitLoss],
          ]
        : [
            ['shares', shares],
            ['cost_amount', costAmount],
            ['profit_loss', profitLoss],
          ];
    for (const [column, value] of boxes) {
      if (value.trim() !== '' && Number.isNaN(Number(value))) {
        setProblem(`${LABELS[column]} 不是有效数字`);
        return;
      }
    }
    const sent = {
      market_value: traded ? number(marketValue) : result.market_value,
      shares: traded || mode === 'amount' ? null : number(shares),
      cost_amount: traded ? null : number(costAmount),
      profit_loss: traded ? null : number(profitLoss),
    };
    upsert.mutate(
      {
        fundCode: fundCode.trim(),
        account_id: accountId,
        ...sent,
        purchase_date: purchaseDate.trim() || null,
        // Whatever the row stored but this restatement does not carry goes back
        // to being derived, so switching 口径 never leaves a stale figure behind.
        reset: traded
          ? []
          : (['shares', 'cost_amount', 'profit_loss'] as const).filter(
              (column) => stored(existing, column) !== null && sent[column] === null,
            ),
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
        <SectionTitle title="同步持仓" />
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
        <PurchaseDateField
          label="首次购买日期"
          value={purchaseDate}
          onChangeText={setPurchaseDate}
        />
        {traded ? (
          <Text style={{ fontSize: 12, color: theme.textMuted, marginBottom: 12 }}>
            这只基金记过 {existing?.trade_count} 笔买卖，份额与持仓成本以流水为准，这里只改持有金额和日期。
          </Text>
        ) : (
          <>
            <View style={{ flexDirection: 'row', marginBottom: 12 }}>
              <Chip label="按金额填" active={mode === 'amount'} onPress={() => setMode('amount')} />
              <Chip label="按份额填" active={mode === 'shares'} onPress={() => setMode('shares')} />
            </View>
            {mode === 'amount' ? (
              <Field
                label="持有金额"
                value={marketValue}
                onChangeText={setMarketValue}
                keyboardType="numeric"
                placeholder="请输入当前持有金额"
              />
            ) : (
              <Field
                label="持有份额"
                value={shares}
                onChangeText={setShares}
                keyboardType="numeric"
                placeholder="请输入持有份额"
              />
            )}
            <Field
              label="持仓成本"
              value={costAmount}
              onChangeText={setCostAmount}
              keyboardType="numeric"
              placeholder="留空则由金额与收益推算"
            />
            <Field
              label="持有收益"
              value={profitLoss}
              onChangeText={setProfitLoss}
              keyboardType="numeric"
              placeholder="留空则由金额与成本推算"
            />
            <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
              {mode === 'shares'
                ? `按最新净值 ${formatNumber(nav, 4)} 换算持有金额。`
                : '填你确定的两个，第三个留空由系统算；清空已填的会改回推算。'}
            </Text>
          </>
        )}
        {problem ? <Text style={{ color: theme.danger, fontSize: 13 }}>{problem}</Text> : null}
      </Card>

      <Card>
        <SectionTitle title="持仓结果" />
        <Row>
          <Stat label="持有金额" value={formatMoney(figures.market_value)} />
          <Stat label="持有份额" value={formatNumber(figures.shares, 2)} tone="muted" />
          <Stat label="持仓成本" value={formatMoney(figures.cost_amount)} tone="muted" />
          <Stat label="平均成本净值" value={formatNumber(figures.average_cost_nav, 4)} tone="muted" />
          <Stat label="持有收益" value={formatSignedMoney(figures.profit_loss)} tone={signTone(figures.profit_loss)} />
          <Stat label="收益率" value={formatSignedRate(figures.profit_loss_rate)} tone={signTone(figures.profit_loss)} />
          <Stat label="持有天数" value={figures.holding_days === null ? '--' : `${figures.holding_days}`} tone="muted" />
        </Row>
      </Card>

      <Card>
        <Button label="保存持仓" onPress={submit} loading={upsert.isPending} />
        <View style={{ flexDirection: 'row', marginTop: 10 }}>
          <View style={{ flex: 1, marginRight: 5 }}>
            <Button
              label="记录买入"
              variant="secondary"
              onPress={() => router.push({ pathname: '/position/trade', params: { code: code, direction: 'BUY' } })}
            />
          </View>
          <View style={{ flex: 1, marginLeft: 5 }}>
            <Button
              label="记录卖出"
              variant="secondary"
              onPress={() => router.push({ pathname: '/position/trade', params: { code: code, direction: 'SELL' } })}
            />
          </View>
        </View>
      </Card>
    </Screen>
  );
}

/** A fund with a BUY/SELL ledger has its money figures owned by the trade records. */
function tradedPosition(existing: PositionItem | null): boolean {
  return (existing?.trade_count ?? 0) > 0;
}

const LABELS = { market_value: '持有金额', shares: '持有份额', cost_amount: '持仓成本', profit_loss: '持有收益' };

type ResolveInput = {
  marketValue: string;
  shares: string;
  costAmount: string;
  profitLoss: string;
  nav: number | null;
  mode: 'amount' | 'shares';
  traded: boolean;
};

/** The same precedence the API uses, so the form shows what saving will store. */
function resolve(input: ResolveInput) {
  const marketValue = number(input.marketValue);
  const shares = number(input.shares);
  const cost = number(input.costAmount);
  const profit = number(input.profitLoss);

  const amount =
    marketValue ?? (input.traded ? null : shares !== null && input.nav ? shares * input.nav : null);
  const held = shares ?? (amount !== null && input.nav ? amount / input.nav : null);
  const basis = input.traded ? cost : (cost ?? (amount !== null && profit !== null ? amount - profit : null));
  const gained = input.traded ? profit : (profit ?? (amount !== null && basis !== null ? amount - basis : null));

  return {
    market_value: amount,
    shares: held,
    cost_amount: basis,
    profit_loss: gained,
    average_cost_nav: basis !== null && held ? basis / held : null,
    profit_loss_rate: gained !== null && basis ? gained / basis : null,
  };
}

/** Days since 首次购买日期, UTC-safe so a device's timezone cannot shift it. */
function daysSince(value: string): number | null {
  if (!isCalendarDate(value)) return null;
  const [year, month, day] = value.trim().split('-').map(Number);
  const then = Date.UTC(year, month - 1, day);
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(Math.round((today - then) / 86_400_000), 0);
}

function number(value: string): number | null {
  return value.trim() === '' || Number.isNaN(Number(value)) ? null : Number(value);
}

/** Only what the row really stores: a derived figure must not prefill a box. */
function snapshotText(
  existing: PositionItem | null,
  column: 'market_value' | 'cost_amount' | 'profit_loss',
): string {
  if (!existing) return '';
  if (column !== 'market_value' && tradedPosition(existing)) return '';
  const derived =
    column === 'cost_amount' ? existing.cost_derived : column === 'profit_loss' ? existing.profit_derived : false;
  return derived ? '' : toInputNumber(existing[column]);
}

function stored(
  existing: PositionItem | null,
  column: 'shares' | 'cost_amount' | 'profit_loss',
): number | null {
  if (!existing || tradedPosition(existing)) return null;
  const derived =
    column === 'shares' ? existing.shares_derived : column === 'cost_amount' ? existing.cost_derived : existing.profit_derived;
  return derived ? null : (existing[column] ?? null);
}

function signTone(value: number | null): 'up' | 'down' | 'muted' {
  if (!value) return 'muted';
  return value > 0 ? 'up' : 'down';
}
