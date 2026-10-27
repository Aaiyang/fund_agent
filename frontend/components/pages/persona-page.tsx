'use client';

import { useState } from 'react';
import { ArrowLeft, Pencil, RefreshCw, ShieldCheck } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type Persona,
  type PersonaFieldKey,
  type PersonaFields,
  type PersonaGroup,
  EXPERIENCE_LEVELS,
  FIELD_LABELS,
  FUND_TYPES,
  PERSONA_GROUPS,
  RESPONSE_DETAILS,
  RESPONSE_LANGUAGES,
  RISK_LEVELS,
  clearPersona,
  countPersonaFields,
  decidePersonaProposal,
  describeChanges,
  formatFieldValue,
  formatOptionLabel,
  getPersonaHistory,
  getUserPersona,
  sourceLabel,
  updatePersona,
} from '@/lib/persona-api';
import { formatDateTime } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

type Tab = 'profile' | 'proposals' | 'history';

export function PersonaPage({
  token,
  onBack,
}: {
  token: string;
  onBack: () => void;
}) {
  const persona = useResource<Persona>(() => getUserPersona(token), token);
  const history = useResource(() => getPersonaHistory(token, 30), token);
  const [tab, setTab] = useState<Tab>('profile');
  const [editing, setEditing] = useState<PersonaGroup | null>(null);
  const [notice, setNotice] = useState('');
  const [problem, setProblem] = useState('');

  if (persona.loading && !persona.data) {
    return (
      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
        <p className="flex items-center gap-2 text-sm text-text-faint">
          <RefreshCw className="size-4 animate-spin text-primary" /> 正在读用户画像…
        </p>
      </div>
    );
  }
  if (persona.error || !persona.data) {
    return (
      <div className="mx-auto max-w-5xl px-5 py-10 sm:px-8">
        <p className="text-sm text-destructive">{persona.error || '暂时读不到画像'}</p>
        <Button variant="outline" className="mt-3 rounded-xl" onClick={() => persona.reload()}>
          重试
        </Button>
      </div>
    );
  }

  const value = persona.data;
  const filled = countPersonaFields(value.fields);
  const groups = Object.keys(PERSONA_GROUPS) as PersonaGroup[];

  async function decide(proposalId: string, decision: 'accept' | 'reject') {
    setProblem('');
    setNotice('');
    try {
      await decidePersonaProposal(token, value.revision, proposalId, decision);
      setNotice(decision === 'accept' ? '已采用建议，后续回答会使用更新后的画像。' : '已忽略这条建议。');
      persona.reload();
      history.reload();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '处理建议失败');
    }
  }

  async function clear() {
    if (
      !window.confirm(
        '清除用户画像？已确认的偏好、待确认建议与变更记录都会删除；聊天记录、长期记忆和持仓不会删除。',
      )
    ) {
      return;
    }
    setProblem('');
    try {
      await clearPersona(token, value.revision);
      setNotice('已清除用户画像，可以重新设置偏好。');
      persona.reload();
      history.reload();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '清除画像失败');
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <section className="mt-5 rounded-[24px] border border-border bg-card/75 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
              AI PERSONALIZATION
            </p>
            <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
              你的偏好，由你决定
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              让基金研究与持仓分析更贴合你的目标和阅读习惯；只有你确认过的内容才会进入画像。
            </p>
          </div>
          <div className="rounded-xl border border-border bg-background/50 px-3 py-2 text-right">
            <p className="text-[10px] text-text-faint">已设置</p>
            <p className="mt-0.5 text-sm font-semibold text-foreground">{filled} / 7 项</p>
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Summary label="风险偏好" value={formatFieldValue('risk_preference', value.fields.risk_preference)} />
          <Summary label="投资期限" value={formatFieldValue('investment_horizon_months', value.fields.investment_horizon_months)} />
          <Summary
            label="投资目标"
            value={value.fields.investment_goals?.length ? `${value.fields.investment_goals.length} 个目标` : '未设置'}
          />
        </div>
        <div className="mt-4 h-1 overflow-hidden rounded-full bg-border">
          <div className="h-full rounded-full bg-primary" style={{ width: `${(filled / 7) * 100}%` }} />
        </div>
      </section>

      <div className="mt-4 flex gap-1 rounded-xl bg-secondary/50 p-1">
        {(
          [
            ['profile', '我的画像'],
            ['proposals', `待确认${value.pending_proposals.length ? ` (${value.pending_proposals.length})` : ''}`],
            ['history', '变更记录'],
          ] as Array<[Tab, string]>
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`flex-1 rounded-lg px-3 py-2 text-xs transition-colors ${
              tab === key
                ? 'bg-card font-medium text-primary shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {notice && (
        <p className="mt-3 rounded-xl bg-primary/[0.06] px-3 py-2 text-xs text-primary">{notice}</p>
      )}
      {problem && (
        <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {problem}
        </p>
      )}

      {tab === 'profile' && (
        <div className="mt-4 space-y-3">
          {groups.map((group, index) => (
            <section key={group} className="rounded-[24px] border border-border bg-card/75 p-5">
              <div className="flex items-start gap-3">
                <span className="grid size-9 place-items-center rounded-xl bg-primary/[0.07] text-[11px] font-semibold text-primary">
                  0{index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-foreground">{PERSONA_GROUPS[group].title}</p>
                  <p className="mt-0.5 text-[11px] text-text-faint">{PERSONA_GROUPS[group].caption}</p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="rounded-lg text-primary"
                  onClick={() => {
                    setEditing(editing === group ? null : group);
                    setNotice('');
                    setProblem('');
                  }}
                >
                  <Pencil /> {editing === group ? '收起' : '编辑'}
                </Button>
              </div>

              {editing === group ? (
                <PersonaEditor
                  key={`${group}:${value.revision}`}
                  token={token}
                  group={group}
                  persona={value}
                  onSaved={() => {
                    setEditing(null);
                    setNotice('已保存，后续回答会使用更新后的偏好。');
                    persona.reload();
                    history.reload();
                  }}
                />
              ) : (
                <div className="mt-3 divide-y divide-border/60">
                  {PERSONA_GROUPS[group].fields.map((key) => (
                    <div key={key} className="flex items-start justify-between gap-4 py-2.5">
                      <div>
                        <p className="text-xs text-muted-foreground">{FIELD_LABELS[key]}</p>
                        {value.provenance[key] && (
                          <p className="mt-0.5 text-[10px] text-text-faint">
                            {sourceLabel(value.provenance[key].source)}
                            {value.provenance[key].confirmed_at
                              ? ` · ${formatDateTime(value.provenance[key].confirmed_at)}`
                              : ''}
                          </p>
                        )}
                      </div>
                      <p className="max-w-[60%] text-right text-xs font-medium text-foreground">
                        {formatFieldValue(key, value.fields[key])}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ))}

          <section className="rounded-[24px] border border-border bg-card/75 p-5">
            <div className="flex items-start gap-3">
              <ShieldCheck className="mt-0.5 size-4 text-primary" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-foreground">数据与隐私</p>
                <p className="mt-1 text-[11px] leading-5 text-text-faint">
                  画像不会代替实际持仓，也不授权交易。清除只删除画像、建议和变更记录，不影响聊天记录与持仓。
                </p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="rounded-lg text-destructive"
                disabled={value.revision === 0 && !value.pending_proposals.length && filled === 0}
                onClick={() => void clear()}
              >
                清除画像
              </Button>
            </div>
          </section>
        </div>
      )}

      {tab === 'proposals' && (
        <div className="mt-4 space-y-3">
          <p className="text-sm font-semibold text-foreground">确认助手理解得是否准确</p>
          <p className="text-xs text-muted-foreground">核对建议和原文依据，选择采用或忽略；你的决定才会改变画像。</p>
          {value.pending_proposals.length === 0 ? (
            <p className="rounded-[24px] border border-dashed border-border bg-card/50 px-5 py-10 text-center text-sm text-muted-foreground">
              没有待确认建议。当你在对话中要求助手记住长期偏好时，建议会出现在这里。
            </p>
          ) : (
            value.pending_proposals.map((proposal) => (
              <section key={proposal.id} className="rounded-[24px] border border-border bg-card/75 p-5">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-semibold text-foreground">画像更新建议</p>
                  <span className="rounded-full bg-primary/[0.08] px-2 py-0.5 text-[10px] text-primary">待你确认</span>
                </div>
                <p className="mt-1 text-[10px] text-text-faint">来自对话 · {formatDateTime(proposal.created_at)}</p>
                <div className="mt-3 space-y-2">
                  {(Object.keys(proposal.changes) as PersonaFieldKey[]).map((key) => (
                    <div key={key} className="rounded-xl border border-border/70 bg-background/40 px-3 py-2">
                      <p className="text-[10px] text-text-faint">{FIELD_LABELS[key] ?? key}</p>
                      <p className="mt-1 text-xs text-text-soft">
                        {formatFieldValue(key, value.fields[key])}
                        <span className="mx-2 text-text-faint">→</span>
                        <span className="font-medium text-primary">
                          {proposal.changes[key] == null ? '清除设置' : formatFieldValue(key, proposal.changes[key])}
                        </span>
                      </p>
                    </div>
                  ))}
                </div>
                <div className="mt-3 rounded-xl bg-secondary/30 px-3 py-2">
                  <p className="text-[10px] text-text-faint">你的原话</p>
                  <p className="mt-1 text-xs leading-5 text-text-soft">“{proposal.evidence}”</p>
                </div>
                <div className="mt-3 flex gap-2">
                  <Button variant="outline" className="h-9 flex-1 rounded-xl" onClick={() => void decide(proposal.id, 'reject')}>
                    忽略
                  </Button>
                  <Button className="h-9 flex-[2] rounded-xl" onClick={() => void decide(proposal.id, 'accept')}>
                    确认采用
                  </Button>
                </div>
              </section>
            ))
          )}
        </div>
      )}

      {tab === 'history' && (
        <div className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
          <p className="text-sm font-semibold text-foreground">每一次改变，都有记录</p>
          <p className="mt-1 text-xs text-muted-foreground">查看你主动设置或确认过的偏好变更。</p>
          {history.loading ? (
            <p className="mt-4 flex items-center gap-2 text-xs text-text-faint">
              <RefreshCw className="size-3.5 animate-spin text-primary" /> 正在读变更记录…
            </p>
          ) : (history.data?.length ?? 0) === 0 ? (
            <p className="mt-4 rounded-xl border border-dashed border-border px-4 py-8 text-center text-xs text-muted-foreground">
              还没有变更记录。设置偏好或采用助手建议后，会在这里显示来源和时间。
            </p>
          ) : (
            <div className="mt-4 space-y-0">
              {history.data?.map((row, index) => (
                <div key={row.revision} className="flex gap-3">
                  <div className="flex flex-col items-center pt-1">
                    <span className="size-2 rounded-full bg-primary" />
                    {index < (history.data?.length ?? 0) - 1 && <span className="mt-1 w-px flex-1 bg-border" />}
                  </div>
                  <div className="flex-1 pb-5">
                    <p className="text-[10px] text-text-faint">{formatDateTime(row.created_at)}</p>
                    <p className="mt-1 text-xs leading-5 text-foreground">{describeChanges(row.changes)}</p>
                    <p className="mt-1 text-[10px] text-text-faint">{sourceLabel(row.source)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-background/40 px-3 py-2">
      <p className="text-[10px] text-text-faint">{label}</p>
      <p className="mt-0.5 text-sm font-semibold text-foreground">{value}</p>
    </div>
  );
}

function PersonaEditor({
  token,
  group,
  persona,
  onSaved,
}: {
  token: string;
  group: PersonaGroup;
  persona: Persona;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<PersonaFields>({ ...persona.fields });
  const [horizon, setHorizon] = useState(
    persona.fields.investment_horizon_months == null
      ? ''
      : String(persona.fields.investment_horizon_months),
  );
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const goals = draft.investment_goals ?? [];

  function change(key: PersonaFieldKey, next: PersonaFields[PersonaFieldKey]) {
    setDraft((current) => ({ ...current, [key]: next }));
    setProblem('');
  }

  function addGoal(text: string) {
    const value = text.trim();
    if (!value) return;
    if (value.length > 120) {
      setProblem('每个目标最多 120 个字。');
      return;
    }
    if (goals.length >= 5) {
      setProblem('最多保留 5 个目标。');
      return;
    }
    if (goals.includes(value)) {
      setProblem('这个目标已经在列表中。');
      return;
    }
    change('investment_goals', [...goals, value]);
    setGoal('');
  }

  async function save() {
    setProblem('');
    const changes: PersonaFields = {};
    for (const key of PERSONA_GROUPS[group].fields as readonly PersonaFieldKey[]) {
      let next = draft[key] ?? null;
      if (key === 'investment_horizon_months') {
        const raw = horizon.trim();
        if (raw && (!/^\d+$/.test(raw) || Number(raw) < 1 || Number(raw) > 600)) {
          setProblem('请输入 1–600 之间的整数月份，或留空。');
          return;
        }
        next = raw ? Number(raw) : null;
      }
      if (Array.isArray(next) && next.length === 0) next = null;
      if (
        JSON.stringify(persona.fields[key] ?? null) !== JSON.stringify(next)
      ) {
        (changes as Record<string, unknown>)[key] = next;
      }
    }
    if (Object.keys(changes).length === 0) {
      onSaved();
      return;
    }
    setBusy(true);
    try {
      await updatePersona(token, persona.revision, changes);
      onSaved();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '保存画像失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-2xl border border-border/70 bg-background/40 p-4">
      {persona.pending_proposals.length > 0 && (
        <p className="mb-3 rounded-xl bg-gold/10 px-3 py-2 text-[11px] leading-5 text-gold">
          保存修改后，现有 {persona.pending_proposals.length} 条待确认建议将失效。
        </p>
      )}

      {group === 'investment' && (
        <div className="space-y-4">
          <ChoiceRow
            title="你对基金投资的熟悉程度"
            options={EXPERIENCE_LEVELS}
            value={draft.investment_experience ?? null}
            field="investment_experience"
            onChange={change}
          />
          <ChoiceRow
            title="你更倾向怎样的投资体验"
            options={RISK_LEVELS}
            value={draft.risk_preference ?? null}
            field="risk_preference"
            onChange={change}
          />
          <div>
            <p className="text-xs font-medium text-foreground">不考虑的基金类型</p>
            <p className="mt-0.5 text-[10px] text-text-faint">可多选；不选表示未设置限制。</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {FUND_TYPES.map((type) => {
                const selected = draft.excluded_fund_types?.includes(type) ?? false;
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() =>
                      change(
                        'excluded_fund_types',
                        selected
                          ? (draft.excluded_fund_types ?? []).filter((item) => item !== type)
                          : [...(draft.excluded_fund_types ?? []), type],
                      )
                    }
                    className={`rounded-full border px-3 py-1 text-[11px] transition-colors ${
                      selected
                        ? 'border-primary/25 bg-primary/[0.08] text-primary'
                        : 'border-border bg-card text-text-soft hover:text-foreground'
                    }`}
                  >
                    {selected ? '✓ ' : ''}
                    {formatOptionLabel('excluded_fund_types', type)}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {group === 'goals' && (
        <div className="space-y-4">
          <div>
            <p className="text-xs font-medium text-foreground">计划投资多久</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {[6, 12, 36, 60].map((months) => (
                <button
                  key={months}
                  type="button"
                  onClick={() => setHorizon(String(months))}
                  className={`rounded-full border px-3 py-1 text-[11px] ${
                    horizon === String(months)
                      ? 'border-primary/25 bg-primary/[0.08] text-primary'
                      : 'border-border bg-card text-text-soft'
                  }`}
                >
                  {months < 12 ? `${months} 个月` : `${months / 12} 年`}
                </button>
              ))}
              <Input
                inputMode="numeric"
                value={horizon}
                onChange={(event) => setHorizon(event.target.value)}
                placeholder="自定义，或留空"
                className="h-8 w-32 rounded-lg bg-card text-xs"
              />
            </div>
            <p className="mt-1 text-[10px] text-text-faint">支持 1–600 个月，留空表示暂未确定。</p>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-foreground">希望实现的目标</p>
              <span className="text-[10px] text-text-faint">{goals.length}/5</span>
            </div>
            <div className="mt-2 space-y-1.5">
              {goals.map((value, index) => (
                <div key={index} className="flex gap-2">
                  <Input
                    value={value}
                    maxLength={120}
                    onChange={(event) =>
                      change(
                        'investment_goals',
                        goals.map((item, position) =>
                          position === index ? event.target.value : item,
                        ),
                      )
                    }
                    className="h-9 rounded-lg bg-card text-xs"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="rounded-lg text-text-faint hover:text-destructive"
                    onClick={() =>
                      change(
                        'investment_goals',
                        goals.filter((_, position) => position !== index),
                      )
                    }
                  >
                    移除
                  </Button>
                </div>
              ))}
              {goals.length < 5 && (
                <div className="flex gap-2">
                  <Input
                    value={goal}
                    maxLength={120}
                    onChange={(event) => setGoal(event.target.value)}
                    placeholder="例如：为三年后的购房做准备"
                    className="h-9 rounded-lg bg-card text-xs"
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') addGoal(goal);
                    }}
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    className="rounded-lg"
                    disabled={!goal.trim()}
                    onClick={() => addGoal(goal)}
                  >
                    添加
                  </Button>
                </div>
              )}
              <div className="flex flex-wrap gap-1.5">
                {['长期积累', '退休储备', '购房准备', '教育规划']
                  .filter((text) => !goals.includes(text))
                  .map((text) => (
                    <button
                      key={text}
                      type="button"
                      onClick={() => addGoal(text)}
                      className="rounded-full border border-border bg-card px-2.5 py-1 text-[10px] text-text-faint hover:text-primary"
                    >
                      ＋ {text}
                    </button>
                  ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {group === 'assistant' && (
        <div className="space-y-4">
          <ChoiceRow
            title="回复语言"
            options={RESPONSE_LANGUAGES}
            value={draft.response_language ?? null}
            field="response_language"
            onChange={change}
          />
          <ChoiceRow
            title="回答详细度"
            options={RESPONSE_DETAILS}
            value={draft.response_detail ?? null}
            field="response_detail"
            onChange={change}
          />
        </div>
      )}

      {problem && <p className="mt-3 text-xs text-destructive">{problem}</p>}
      <div className="mt-4 flex gap-2">
        <Button variant="outline" className="h-9 rounded-xl" disabled={busy} onClick={onSaved}>
          取消
        </Button>
        <Button className="h-9 rounded-xl" disabled={busy} onClick={() => void save()}>
          {busy ? <RefreshCw className="animate-spin" /> : null} 保存修改
        </Button>
      </div>
    </div>
  );
}

function ChoiceRow({
  title,
  options,
  value,
  field,
  onChange,
}: {
  title: string;
  options: readonly string[];
  value: string | null;
  field: PersonaFieldKey;
  onChange: (field: PersonaFieldKey, value: PersonaFields[PersonaFieldKey]) => void;
}) {
  return (
    <div>
      <p className="text-xs font-medium text-foreground">{title}</p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(field, option as PersonaFields[PersonaFieldKey])}
            className={`rounded-full border px-3 py-1 text-[11px] transition-colors ${
              value === option
                ? 'border-primary/25 bg-primary/[0.08] text-primary'
                : 'border-border bg-card text-text-soft hover:text-foreground'
            }`}
          >
            {formatOptionLabel(field, option)}
          </button>
        ))}
        <button
          type="button"
          onClick={() => onChange(field, null)}
          className={`rounded-full border px-3 py-1 text-[11px] ${
            value === null
              ? 'border-primary/25 bg-primary/[0.08] text-primary'
              : 'border-border bg-card text-text-faint'
          }`}
        >
          暂不设置
        </button>
      </div>
    </div>
  );
}
