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
  const [shares, setShares] = useState(snapshotText(existing, 'shares'));
  const [costNav, setCostNav] = useState(snapshotText(existing, 'average_cost_nav'));
  const [problem, setProblem] = useState<string | null>(null);

  const nav = detail.data?.latest_nav ?? existing?.unit_nav ?? null;
  const days = daysSince(purchaseDate);
  const typed = resolve({
    marketValue,
    shares,
    costNav,
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
            ['average_cost_nav', costNav],
          ]
        : [
            ['shares', shares],
            ['average_cost_nav', costNav],
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
      average_cost_nav: traded ? null : number(costNav),
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
          : (['shares', 'average_cost_nav'] as const).filter(
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
              label="持有成本"
              value={costNav}
              onChangeText={setCostNav}
              keyboardType="numeric"
              placeholder="请输入持仓成本净值"
            />
            <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
              {mode === 'shares'
                ? `按最新净值 ${formatNumber(nav, 4)} 换算持有金额，成本 = 成本净值 × 份额。`
                : '份额按最新净值折算，成本 = 成本净值 × 份额，收益 = 金额 − 成本。'}
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
      </Card>

      <Card>
        <SectionTitle title="加减仓" action="定投计划" onAction={() => router.push('/auto-invest')} />
        <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
          {TRADE_ACTIONS.map((action) => (
            <View key={action.operation} style={{ flexBasis: '50%', paddingHorizontal: 5, marginBottom: 10 }}>
              <Button
                label={action.label}
                variant="secondary"
                onPress={() =>
                  router.push({ pathname: '/position/trade', params: { code: code, operation: action.operation } })
                }
              />
            </View>
          ))}
        </View>
      </Card>
    </Screen>
  );
}

const TRADE_ACTIONS: { operation: 'BUY' | 'SELL' | 'AUTO_INVEST' | 'CONVERT'; label: string }[] = [
  { operation: 'BUY', label: '同步加仓' },
  { operation: 'SELL', label: '同步减仓' },
  { operation: 'AUTO_INVEST', label: '同步定投' },
  { operation: 'CONVERT', label: '同步转换' },
];

/** A fund with a BUY/SELL ledger has its money figures owned by the trade records. */
function tradedPosition(existing: PositionItem | null): boolean {
  return (existing?.trade_count ?? 0) > 0;
}

const LABELS = { market_value: '持有金额', shares: '持有份额', average_cost_nav: '持有成本' };

type ResolveInput = {
  marketValue: string;
  shares: string;
  costNav: string;
  /** What the row already carries, so the card is not blank until he types. */
  storedCost: number | null;
  nav: number | null;
  mode: 'amount' | 'shares';
  traded: boolean;
};

/** The same precedence the API uses, so the form shows what saving will store. */
function resolve(input: ResolveInput) {
  const marketValue = number(input.marketValue);
  const shares = number(input.shares);
  const costNav = number(input.costNav);

  const amount = marketValue ?? (input.traded ? null : shares !== null && input.nav ? shares * input.nav : null);
  const held = shares ?? (amount !== null && input.nav ? amount / input.nav : null);
  // 持仓成本价 is the input; the money still in the fund is that price times the
  // units, and until he states one the row's own figure is the honest answer.
  const basis = costNav !== null && held ? costNav * held : input.storedCost;
  const gained = amount !== null && basis !== null ? amount - basis : null;

  return {
    market_value: amount,
    shares: held,
    cost_amount: basis,
    average_cost_nav: costNav ?? (basis !== null && held ? basis / held : null),
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

/** The three columns a snapshot box can read from. */
type BoxColumn = 'market_value' | 'shares' | 'average_cost_nav';

/** 持有金额 is the anchor and never derived; the other two may be. */
function isDerived(existing: PositionItem, column: BoxColumn): boolean {
  if (column === 'shares') return Boolean(existing.shares_derived);
  if (column === 'average_cost_nav') return Boolean(existing.average_cost_nav_derived);
  return false;
}

/** Only what the row really stores: a derived figure must not prefill a box. */
function snapshotText(existing: PositionItem | null, column: BoxColumn): string {
  if (!existing || isDerived(existing, column)) return '';
  if (tradedPosition(existing) && column !== 'market_value') return '';
  return toInputNumber(existing[column], column === 'average_cost_nav' ? 4 : 2);
}

function stored(existing: PositionItem | null, column: Exclude<BoxColumn, 'market_value'>): number | null {
  if (!existing || tradedPosition(existing) || isDerived(existing, column)) return null;
  return existing[column] ?? null;
}

function signTone(value: number | null): 'up' | 'down' | 'muted' {
  if (!value) return 'muted';
  return value > 0 ? 'up' : 'down';
}
