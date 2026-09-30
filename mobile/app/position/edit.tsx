import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { FundReference } from '@/components/FundReference';
import { PurchaseDateField, initialPurchaseDate, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { LoadingState, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Row, Screen, SectionTitle, Stat } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useFundDetail } from '@/hooks/useFunds';
import { useAccounts, useDeletePosition, usePosition, useUpsertPosition, type PositionItem } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import { confirmAction } from '@/utils/confirm';
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
  const remove = useDeletePosition();
  const code = initialCode.trim();
  const detail = useFundDetail(code.length === 6 ? code : null);
  const [purchaseDate, setPurchaseDate] = useState(
    initialPurchaseDate(existing?.purchase_date, existing?.created_at ?? existing?.updated_at),
  );
  // A ledger owns these columns, so the snapshot keeps only what it may still
  // correct: the value on screen and the day the holding started.
  const traded = tradedPosition(existing);
  const [mode, setMode] = useState<'amount' | 'shares'>('amount');
  const [marketValue, setMarketValue] = useState(snapshotText(existing, 'market_value'));
  const [shares, setShares] = useState(snapshotText(existing, 'shares'));
  const [costNav, setCostNav] = useState(snapshotText(existing, 'average_cost_nav'));
  const [profitLoss, setProfitLoss] = useState(snapshotText(existing, 'profit_loss'));
  const [problem, setProblem] = useState<string | null>(null);

  const nav = detail.data?.latest_nav ?? existing?.unit_nav ?? null;
  const days = daysSince(purchaseDate);
  const typed = resolve({
    marketValue,
    shares,
    costNav,
    profitLoss,
    storedCost: existing?.cost_amount ?? null,
    nav,
    mode,
    traded,
  });
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
  // An all-blank result card is noise: it only earns its space once a figure
  // actually resolves, from what he typed or from the row he is editing.
  const hasMoney = [
    figures.market_value,
    figures.shares,
    figures.cost_amount,
    figures.average_cost_nav,
    figures.profit_loss,
    figures.profit_loss_rate,
  ].some((value) => value !== null);

  function drop() {
    if (accountId === null || !existing) {
      return;
    }
    confirmAction(
      '删除持仓',
      `${code} 在本账户的持仓、全部流水和定投计划都会被删除，不可恢复。`,
      () =>
        remove.mutate(
          { accountId, fundCode: code },
          {
            onSuccess: () => router.back(),
            onError: (error) => setProblem(describeError(error)),
          },
        ),
    );
  }

  function submit() {
    setProblem(null);
    if (accountId === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    const dateProblem = purchaseDateProblem(purchaseDate);
    if (dateProblem) {
      setProblem(dateProblem);
      return;
    }
    const values: Record<SendColumn, string> = {
      market_value: marketValue,
      shares,
      average_cost_nav: costNav,
      profit_loss: profitLoss,
    };
    for (const column of shownColumns(mode, traded)) {
      if (values[column].trim() !== '' && Number.isNaN(Number(values[column]))) {
        setProblem(`${LABELS[column]} 不是有效数字`);
        return;
      }
    }
    const sent: Record<SendColumn, number | null> = {
      market_value: traded ? number(marketValue) : result.market_value,
      shares: !traded && mode === 'shares' ? number(shares) : null,
      average_cost_nav: !traded && mode === 'shares' ? number(costNav) : null,
      profit_loss: !traded && mode === 'amount' ? number(profitLoss) : null,
    };
    upsert.mutate(
      {
        fundCode: code,
        account_id: accountId,
        ...sent,
        purchase_date: purchaseDate.trim() || null,
        // Whatever the row stored but this restatement does not carry goes back
        // to being derived, so switching 口径 never leaves a stale figure behind.
        reset: traded
          ? []
          : (['shares', 'average_cost_nav', 'profit_loss'] as const).filter(
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
        <FundReference
          code={code}
          name={detail.data?.fund_name ?? existing?.fund_name}
          nav={detail.data?.latest_nav ?? existing?.unit_nav}
          navDate={detail.data?.nav_date ?? existing?.nav_date}
          dailyReturn={detail.data?.daily_return ?? existing?.daily_return}
          note={
            existing
              ? `已持有：市值 ${formatMoney(existing.market_value)}`
              : '该账户下还没有这只基金的持仓'
          }
        />
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
            {shownColumns(mode, traded).map((column) => (
              <Field
                key={column}
                label={LABELS[column]}
                value={{ market_value: marketValue, shares, average_cost_nav: costNav, profit_loss: profitLoss }[column]}
                onChangeText={{
                  market_value: setMarketValue,
                  shares: setShares,
                  average_cost_nav: setCostNav,
                  profit_loss: setProfitLoss,
                }[column]}
                keyboardType="numeric"
                placeholder={`请输入${LABELS[column]}`}
              />
            ))}
            <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
              {mode === 'shares'
                ? `金额按最新净值 ${formatNumber(nav, 4)} 折算，成本 = 成本净值 × 份额。`
                : `份额按最新净值 ${formatNumber(nav, 4)} 折算，成本 = 金额 − 收益。`}
            </Text>
          </>
        )}
        {problem ? <Text style={{ color: theme.danger, fontSize: 13 }}>{problem}</Text> : null}
      </Card>

      {hasMoney ? (
        <Card>
          <SectionTitle title="持仓结果" action={existing ? '删除持仓' : undefined} onAction={drop} />
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
      ) : null}

      <Card>
        <Button label="保存持仓" onPress={submit} loading={upsert.isPending} />
      </Card>

      <Card>
        <SectionTitle title="加减仓" action="定投计划" onAction={() => router.push('/auto-invest')} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {TRADE_ACTIONS.map((action) => (
            <View key={action.label} style={{ flexBasis: '50%', paddingHorizontal: 5, marginBottom: 10 }}>
              <Button
                label={action.label}
                variant="secondary"
                onPress={() =>
                  router.push({ pathname: '/position/trade', params: { code, operation: action.operation } })
                }
              />
            </View>
          ))}
        </View>
      </Card>
    </Screen>
  );
}

/**
 * All four add to or take away from the holding that is already there. 定投 is
 * one of them — a debit that already happened — but it fixes its own day to
 * today, so it asks for an amount only. The recurring schedule lives on the
 * 定投计划 page, reached from the card's own action.
 */
const TRADE_ACTIONS: { label: string; operation: 'BUY' | 'SELL' | 'AUTO_INVEST' | 'CONVERT' }[] = [
  { label: '同步加仓', operation: 'BUY' },
  { label: '同步减仓', operation: 'SELL' },
  { label: '同步定投', operation: 'AUTO_INVEST' },
  { label: '同步转换', operation: 'CONVERT' },
];

/** A fund with a BUY/SELL ledger has its money figures owned by the trade records. */
function tradedPosition(existing: PositionItem | null): boolean {
  return (existing?.trade_count ?? 0) > 0;
}

type Mode = 'amount' | 'shares';

/** The four money columns, and the label each box shows. */
type SendColumn = 'market_value' | 'shares' | 'average_cost_nav' | 'profit_loss';

const LABELS: Record<SendColumn, string> = {
  market_value: '持有金额',
  shares: '持有份额',
  average_cost_nav: '持有成本（净值）',
  profit_loss: '持有收益',
};

/**
 * Which pair a 口径 shows. A holdings screen lists 金额 next to 收益 and 份额
 * next to 成本价, so each side reads off the pair it already has; the other
 * figures follow from it and stay read-only.
 */
function shownColumns(mode: Mode, traded: boolean): SendColumn[] {
  if (traded) return ['market_value'];
  return mode === 'amount' ? ['market_value', 'profit_loss'] : ['shares', 'average_cost_nav'];
}

type ResolveInput = {
  marketValue: string;
  shares: string;
  costNav: string;
  profitLoss: string;
  /** What the row already carries, so the card is not blank until he types. */
  storedCost: number | null;
  nav: number | null;
  mode: Mode;
  traded: boolean;
};

/** The same precedence the API uses, so the form shows what saving will store. */
function resolve(input: ResolveInput) {
  // Only the visible boxes count: a figure typed in the other 口径 and then
  // switched away from must not keep steering the result from off screen.
  const byAmount = input.mode === 'amount' || input.traded;
  const typedAmount = number(input.marketValue);
  const typedShares = number(input.shares);
  const typedCostNav = number(input.costNav);
  const typedProfit = number(input.profitLoss);

  const amount = byAmount ? typedAmount : (typedShares !== null && input.nav ? typedShares * input.nav : null);
  const held = byAmount
    ? amount !== null && input.nav
      ? amount / input.nav
      : null
    : typedShares ?? (amount !== null && input.nav ? amount / input.nav : null);
  const profit = byAmount ? typedProfit : null;
  const costNav = byAmount ? null : typedCostNav;

  const basis =
    profit !== null && amount !== null
      ? amount - profit
      : costNav !== null && held
        ? costNav * held
        : input.storedCost;
  const gained = profit ?? (amount !== null && basis !== null ? amount - basis : null);
  const price = costNav ?? (basis !== null && held ? basis / held : null);

  return {
    market_value: amount,
    shares: held,
    cost_amount: basis,
    average_cost_nav: price,
    profit_loss: gained,
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

/** 持有金额 is the anchor; the other three can each be implied by the rest. */
function isDerived(existing: PositionItem, column: SendColumn): boolean {
  if (column === 'shares') return Boolean(existing.shares_derived);
  if (column === 'average_cost_nav') return Boolean(existing.average_cost_nav_derived);
  if (column === 'profit_loss') return Boolean(existing.profit_derived);
  return false;
}

/** Only what the row really stores: a derived figure must not prefill a box. */
function snapshotText(existing: PositionItem | null, column: SendColumn): string {
  if (!existing || isDerived(existing, column)) return '';
  if (tradedPosition(existing) && column !== 'market_value') return '';
  return toInputNumber(existing[column], column === 'average_cost_nav' ? 4 : 2);
}

function stored(existing: PositionItem | null, column: Exclude<SendColumn, 'market_value'>): number | null {
  if (!existing || tradedPosition(existing) || isDerived(existing, column)) return null;
  return existing[column] ?? null;
}

function signTone(value: number | null): 'up' | 'down' | 'muted' {
  if (!value) return 'muted';
  return value > 0 ? 'up' : 'down';
}
