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
 * 同步持仓：把第三方持仓页上的数字转述进来（spec 3.7.1）。
 *
 * 这是快照通道、不是交易通道——这里没有任何数字按日期定价。
 * 三个金额是用户从屏幕上直接读到的，第四个能由它们推出，所以表单
 * 自动算出他没填的那一侧，作为结果展示，而不是再多给一个输入框。
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

  // 账户或存量版本号一变就重新挂载表单、重新灌入初值，
  // 因此不需要任何 effect 把查询数据拷进字段状态。
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
  // 有流水后这些列就归流水管，快照通道只保留它仍有权修正的两项：
  // 屏幕上的市值，以及持仓起始的那一天。
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
  // 有流水时，用户改不了的数字仍由买卖流水累加得出，所以结果卡片
  // 在他那一个输入框旁边如实展示这些值，而不是留白。
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
  // 全空的结果卡片纯属噪音：只有当至少一个数字真的算得出来——
  // 来自他填的内容或正在编辑的那一行——它才配占这块地方。
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
            onSuccess: () => router.replace('/(tabs)'),
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
        // 行里原本存了、但这次重述没有带过去的列，一律退回派生值，
        // 这样切换口径后不会留下过期的旧数字。
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
 * 这四种操作都在既有持仓上做了加减。定投也是其中之一——一笔已经发生的扣款——
 * 但它把扣款日固定为今天，所以只问金额。周期性排期在定投计划页维护，
 * 从这张卡片自己的入口进去。
 */
const TRADE_ACTIONS: { label: string; operation: 'BUY' | 'SELL' | 'AUTO_INVEST' | 'CONVERT' }[] = [
  { label: '同步加仓', operation: 'BUY' },
  { label: '同步减仓', operation: 'SELL' },
  { label: '同步定投', operation: 'AUTO_INVEST' },
  { label: '同步转换', operation: 'CONVERT' },
];

/** 基金一旦有了买入/卖出流水，金额类数字就归交易流水说了算。 */
function tradedPosition(existing: PositionItem | null): boolean {
  return (existing?.trade_count ?? 0) > 0;
}

type Mode = 'amount' | 'shares';

/** 四个金额列，以及每个输入框显示的标签。 */
type SendColumn = 'market_value' | 'shares' | 'average_cost_nav' | 'profit_loss';

const LABELS: Record<SendColumn, string> = {
  market_value: '持有金额',
  shares: '持有份额',
  average_cost_nav: '持有成本（净值）',
  profit_loss: '持有收益',
};

/**
 * 每种口径展示哪一对输入框。持仓页面通常金额挨着收益、份额挨着成本价，
 * 用户照着手里已有的那一对填即可；其余数字由这一对推出来，保持只读。
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
  /** 该行已有的存量值，这样用户还没输入时结果卡片不至于全空。 */
  storedCost: number | null;
  nav: number | null;
  mode: Mode;
  traded: boolean;
};

/** 与 API 相同的取值优先级，保证表单预览的就是保存后真正落库的值。 */
function resolve(input: ResolveInput) {
  // 只有当前可见的输入框参与计算：在另一种口径下填过、之后又切走的数字，
  // 不能在屏幕外继续左右结果。
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

/** 距首次购买日期的天数；全程按 UTC 计算，设备时区改动不了它。 */
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

/** 持有金额是锚定值；其余三列都能由剩下的数字反推出来。 */
function isDerived(existing: PositionItem, column: SendColumn): boolean {
  if (column === 'shares') return Boolean(existing.shares_derived);
  if (column === 'average_cost_nav') return Boolean(existing.average_cost_nav_derived);
  if (column === 'profit_loss') return Boolean(existing.profit_derived);
  return false;
}

/** 只回填该行真正存储的值：派生出来的数字不能预填进输入框。 */
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
