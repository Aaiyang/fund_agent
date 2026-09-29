import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { Async, describeError } from '@/components/states';
import { Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAutoInvestPlans, useCreatePlan, useDeletePlan, useUpdatePlan, type AutoInvestPlan } from '@/hooks/useAutoInvest';
import { useUiStore } from '@/stores/ui';
import { formatDate, formatMoney, localToday } from '@/utils/format';

type Frequency = 'daily' | 'weekly' | 'biweekly' | 'monthly';

/** `max` is the day-number range; 每天 has no day to name, so it has none. */
const FREQUENCIES: { key: Frequency; label: string; max: number | null }[] = [
  { key: 'daily', label: '每天', max: null },
  { key: 'weekly', label: '每周', max: 7 },
  { key: 'biweekly', label: '每两周', max: 7 },
  { key: 'monthly', label: '每月', max: 31 },
];

const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

/** 定投计划: the schedule, and what it has already bought. */
export default function AutoInvestScreen() {
  const accountId = useUiStore((state) => state.accountId);
  const plans = useAutoInvestPlans(accountId);
  const create = useCreatePlan();
  const [creating, setCreating] = useState(false);

  return (
    <Screen>
      <Async query={plans} empty={() => <Text style={{ fontSize: 13, color: theme.textMuted }}>还没有定投计划</Text>}>
        {(data) => (
          <>
            {data.items.map((plan) => (
              <PlanCard key={plan.id} plan={plan} />
            ))}
            {(data.settled ?? 0) > 0 ? (
              <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 10 }}>
                本次打开补记了 {data.settled} 期定投扣款。
              </Text>
            ) : null}
          </>
        )}
      </Async>

      <Card>
        <Button
          label={creating ? '收起新建计划' : '+ 新建定投计划'}
          variant={creating ? 'secondary' : 'primary'}
          onPress={() => setCreating(!creating)}
        />
      </Card>

      {creating ? <CreatePlan accountId={accountId} create={create} onDone={() => setCreating(false)} /> : null}
    </Screen>
  );
}

function PlanCard({ plan }: { plan: AutoInvestPlan }) {
  const update = useUpdatePlan();
  const remove = useDeletePlan();
  const [problem, setProblem] = useState<string | null>(null);

  return (
    <Card style={{ opacity: plan.active ? 1 : 0.55 }}>
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }} numberOfLines={1}>
        {plan.fund_name ?? plan.fund_code}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
        {plan.fund_code} · {describe(plan.frequency, plan.run_day)} {formatMoney(plan.amount)}
      </Text>
      <Text style={{ fontSize: 13, color: theme.text, marginTop: 8 }}>
        {plan.active ? `下期 ${formatDate(plan.next_due)}` : '已暂停'}
        {plan.last_run_date ? ` · 上次扣款 ${formatDate(plan.last_run_date)}` : ''}
      </Text>
      {plan.end_date ? (
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>到 {formatDate(plan.end_date)} 止</Text>
      ) : null}
      <View style={{ flexDirection: 'row', marginTop: 10 }}>
        <View style={{ flex: 1, marginRight: 5 }}>
          <Button
            label={plan.active ? '暂停' : '启用'}
            variant="secondary"
            loading={update.isPending}
            onPress={() =>
              update.mutate(
                { planId: plan.id, active: !plan.active },
                { onError: (error) => setProblem(describeError(error)) },
              )
            }
          />
        </View>
        <View style={{ flex: 1, marginLeft: 5 }}>
          <Button
            label="删除"
            variant="danger"
            loading={remove.isPending}
            onPress={() =>
              remove.mutate(
                // Installments are money that really moved, so they only go
                // with the plan when the plan itself was a mistake.
                { planId: plan.id, withOrders: false },
                { onError: (error) => setProblem(describeError(error)) },
              )
            }
          />
        </View>
      </View>
      {problem ? <Text style={{ fontSize: 12, color: theme.danger, marginTop: 8 }}>{problem}</Text> : null}
    </Card>
  );
}

function CreatePlan({
  accountId,
  create,
  onDone,
}: {
  accountId: number | null;
  create: ReturnType<typeof useCreatePlan>;
  onDone: () => void;
}) {
  const [fundCode, setFundCode] = useState('');
  const [amount, setAmount] = useState('');
  const [frequency, setFrequency] = useState<Frequency>('weekly');
  const [runDay, setRunDay] = useState('1');
  const [startDate, setStartDate] = useState(localToday());
  const [problem, setProblem] = useState<string | null>(null);
  const max = FREQUENCIES.find((entry) => entry.key === frequency)?.max ?? null;

  function submit() {
    setProblem(null);
    if (accountId === null) {
      setProblem('请先在首页选择一个账户');
      return;
    }
    if (!/^\d{6}$/.test(fundCode.trim())) {
      setProblem('基金代码需要是 6 位数字');
      return;
    }
    if (amount.trim() === '' || Number(amount) <= 0) {
      setProblem('请填写每期定投金额');
      return;
    }
    const day = max === null ? 1 : Number(runDay);
    if (max !== null && (!Number.isInteger(day) || day < 1 || day > max)) {
      setProblem(`扣款日要在 1-${max} 之间`);
      return;
    }
    create.mutate(
      {
        account_id: accountId,
        fund_code: fundCode.trim(),
        amount: Number(amount),
        frequency,
        run_day: day,
        start_date: startDate,
      },
      {
        onSuccess: onDone,
        onError: (error) =>
          setProblem(
            error instanceof ApiError && error.status === 422 ? error.message : describeError(error),
          ),
      },
    );
  }

  return (
    <Card>
      <SectionTitle title="新建定投计划" />
      <Field label="基金代码" value={fundCode} onChangeText={setFundCode} keyboardType="numeric" placeholder="请输入基金代码" />
      <Field label="每期定投金额" value={amount} onChangeText={setAmount} keyboardType="numeric" placeholder="请输入金额" />
      <View style={{ flexDirection: 'row', marginBottom: 12 }}>
        {FREQUENCIES.map((entry) => (
          <Chip key={entry.key} label={entry.label} active={frequency === entry.key} onPress={() => setFrequency(entry.key)} />
        ))}
      </View>
      {max !== null ? (
        <Field
          label={frequency === 'monthly' ? '每月几号扣款（1-31）' : '星期几扣款（1=周一 … 7=周日）'}
          value={runDay}
          onChangeText={setRunDay}
          keyboardType="numeric"
          placeholder={frequency === 'monthly' ? '请输入 1-31' : '请输入 1-7'}
        />
      ) : null}
      <Field label="开始日期" value={startDate} onChangeText={setStartDate} placeholder="YYYY-MM-DD" />
      <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
        到期后打开这个页面就会补成买入流水；净值还没公布的那一期会留到下次。
      </Text>
      {problem ? <Text style={{ fontSize: 12, color: theme.danger, marginBottom: 10 }}>{problem}</Text> : null}
      <Button label="创建计划" onPress={submit} loading={create.isPending} />
    </Card>
  );
}

function describe(frequency: string, runDay: number): string {
  if (frequency === 'daily') return '每天';
  if (frequency === 'monthly') return `每月 ${runDay} 号`;
  const label = FREQUENCIES.find((entry) => entry.key === frequency)?.label ?? frequency;
  return `${label} ${WEEKDAYS[runDay - 1] ?? runDay}`;
}
