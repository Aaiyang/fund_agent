/**
 * 用户画像（`/agent/user-profile`）.
 *
 * 口径要拎清：画像里只有**用户自己声明的偏好**，没有持仓、金额、凭证或交易授权；
 * Agent 从对话里推断出来的东西一律只能当「候选」，必须人工点确认才会进画像。
 * 每次变更推一版 `revision`，写操作都要带上读到的版本号，版本对不上后端回 409。
 *
 * 类型与 `backend/app/schemas/user_persona.py` 一一对应：openapi 生成物
 * `mobile/api/schema.ts` 里还没有这批接口，所以这里手写；等下次
 * `npm run generate:api` 之后可以换成 `components['schemas'][...]`。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiError, api, request } from '@/api/client';
import { queryKeys } from '@/api/queries';

export type FundType =
  | 'equity'
  | 'bond'
  | 'money_market'
  | 'mixed'
  | 'index'
  | 'qdii'
  | 'fof'
  | 'reit'
  | 'commodity';

export type PersonaFieldKey =
  | 'response_language'
  | 'response_detail'
  | 'investment_experience'
  | 'risk_preference'
  | 'investment_horizon_months'
  | 'investment_goals'
  | 'excluded_fund_types';

export type PersonaFields = {
  response_language?: 'zh-CN' | 'en' | null;
  response_detail?: 'concise' | 'balanced' | 'detailed' | null;
  investment_experience?: 'beginner' | 'intermediate' | 'experienced' | null;
  risk_preference?: 'conservative' | 'balanced' | 'aggressive' | null;
  investment_horizon_months?: number | null;
  investment_goals?: string[] | null;
  excluded_fund_types?: FundType[] | null;
};

export type PersonaProvenance = {
  source?: string;
  confirmed_at?: string;
  revision?: number;
  proposal_id?: string;
};

export type PersonaProposal = {
  id: string;
  base_revision: number;
  changes: PersonaFields;
  evidence: string;
  source_session_id: string;
  source_message_id: string;
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'SUPERSEDED';
  created_at: string;
};

export type Persona = {
  revision: number;
  fields: PersonaFields;
  provenance: Record<string, PersonaProvenance>;
  pending_proposals: PersonaProposal[];
};

export type PersonaHistory = {
  revision: number;
  changes: PersonaFields;
  source: string;
  proposal_id?: string | null;
  created_at: string;
};

/** 字段在界面上的叫法，顺序也决定候选/历史里逐行展示的顺序。 */
export const FIELD_LABELS: Record<PersonaFieldKey, string> = {
  response_language: '回复语言',
  response_detail: '回答详细度',
  investment_experience: '投资经验',
  risk_preference: '风险偏好',
  investment_horizon_months: '投资期限（月）',
  investment_goals: '投资目标',
  excluded_fund_types: '不考虑的基金类型',
};

const OPTION_LABELS: Record<string, string> = {
  'zh-CN': '中文',
  en: 'English',
  concise: '简洁',
  balanced: '适中',
  detailed: '详细',
  beginner: '新手',
  intermediate: '有一定经验',
  experienced: '熟练',
  conservative: '稳健',
  aggressive: '进取',
};

export const FUND_TYPE_LABELS: Record<FundType, string> = {
  equity: '股票型',
  bond: '债券型',
  money_market: '货币型',
  mixed: '混合型',
  index: '指数型',
  qdii: 'QDII',
  fof: 'FOF',
  reit: 'REITs',
  commodity: '商品型',
};

/** 后端 `_apply` 只会写这两种来源，别的取值原样显示，不替它编故事。 */
const SOURCE_LABELS: Record<string, string> = {
  user_edit: '我自己填的',
  user_confirmed_proposal: '确认过 Agent 的提议',
};

export const RESPONSE_LANGUAGES: ('zh-CN' | 'en')[] = ['zh-CN', 'en'];
export const RESPONSE_DETAILS: ('concise' | 'balanced' | 'detailed')[] = ['concise', 'balanced', 'detailed'];
export const EXPERIENCE_LEVELS: ('beginner' | 'intermediate' | 'experienced')[] = [
  'beginner',
  'intermediate',
  'experienced',
];
export const RISK_LEVELS: ('conservative' | 'balanced' | 'aggressive')[] = ['conservative', 'balanced', 'aggressive'];
export const FUND_TYPES: FundType[] = [
  'equity',
  'bond',
  'money_market',
  'mixed',
  'index',
  'qdii',
  'fof',
  'reit',
  'commodity',
];

/** 投资目标的条数与单条长度上限照后端 schema（最多 5 条，每条 1-120 字）。 */
export const GOALS_MAX = 5;
export const GOAL_TEXT_MAX = 120;
export const HORIZON_MIN = 1;
export const HORIZON_MAX = 600;

export function sourceLabel(source?: string): string {
  if (!source) return '来源未知';
  return SOURCE_LABELS[source] ?? source;
}

/**
 * 单个取值念成中文。
 *
 * `balanced` 在「回答详细度」里是"适中"、在「风险偏好」里是"平衡"，同一个裸值
 * 两个意思，所以必须按字段翻，不能共用一张表。
 */
export function formatOptionLabel(key: PersonaFieldKey, value: string): string {
  if (key === 'excluded_fund_types') return FUND_TYPE_LABELS[value as FundType] ?? value;
  if (key === 'risk_preference' && value === 'balanced') return '平衡';
  return OPTION_LABELS[value] ?? value;
}

export function formatFieldValue(key: PersonaFieldKey, value: PersonaFields[PersonaFieldKey]): string {
  if (value === null || value === undefined) return '未设置';
  if (key === 'investment_horizon_months') return `${value} 个月`;
  if (Array.isArray(value)) {
    if (value.length === 0) return '无';
    return value.map((item) => formatOptionLabel(key, String(item))).join('、');
  }
  return formatOptionLabel(key, String(value));
}

/** 候选与历史里的 `changes` 是自由 dict，逐字段拼成「标签：值」一行. */
export function describeChanges(changes: PersonaFields | Record<string, unknown>): string {
  const entries = Object.entries(changes ?? {}) as [PersonaFieldKey, PersonaFields[PersonaFieldKey]][];
  const lines = entries.map(([key, value]) => `${FIELD_LABELS[key] ?? key}：${formatFieldValue(key, value)}`);
  return lines.length > 0 ? lines.join('；') : '（没有字段变化）';
}

export function useUserPersona() {
  return useQuery({
    queryKey: queryKeys.userPersona,
    queryFn: () => api.get<Persona>('/agent/user-profile'),
  });
}

export function useUserPersonaHistory(limit: number) {
  return useQuery({
    queryKey: [...queryKeys.userPersonaHistory, limit],
    queryFn: () => api.get<PersonaHistory[]>('/agent/user-profile/history', { limit }),
  });
}

/** 写操作全部要把读到的版本交回去，冲突时后端拒绝而不是静默覆盖。 */
function withRevision<T extends object>(revision: number, body: T) {
  return { ...body, expected_revision: revision };
}

/**
 * 写操作成功后**不重新 GET**：后端每个写接口都返回完整的最新画像，直接把它写进
 * 缓存就行。这批接口共用 `/agent` 那条限流（10 次/分钟），每次保存再多打一个 GET
 * 的话，用户连点四五下就会自己把额度吃光。
 *
 * 变更历史单独一条限流，且它只是审计列表，所以交给失效重取。
 */
async function applyPersona(client: ReturnType<typeof useQueryClient>, persona: Persona) {
  client.setQueryData(queryKeys.userPersona, persona);
  await client.invalidateQueries({ queryKey: queryKeys.userPersonaHistory });
}

/** Conflict refreshes the server snapshot without overwriting an open editor's draft. */
async function refreshPersonaOnConflict(client: ReturnType<typeof useQueryClient>, error: unknown) {
  if (error instanceof ApiError && error.status === 409) {
    await client.invalidateQueries({ queryKey: queryKeys.userPersona });
  }
}

export function usePersonaUpdate(revision: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (changes: PersonaFields) => api.patch<Persona>('/agent/user-profile', withRevision(revision, { changes })),
    onSuccess: (persona) => applyPersona(client, persona),
    onError: (error) => refreshPersonaOnConflict(client, error),
  });
}

export function usePersonaDecision(revision: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ proposalId, decision }: { proposalId: string; decision: 'accept' | 'reject' }) =>
      api.post<Persona>(`/agent/user-profile/proposals/${proposalId}/decision`, withRevision(revision, { decision })),
    onSuccess: (persona) => applyPersona(client, persona),
    onError: (error) => refreshPersonaOnConflict(client, error),
  });
}

export function usePersonaClear(revision: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => request<Persona>('/agent/user-profile', { method: 'DELETE', body: withRevision(revision, {}) }),
    onSuccess: (persona) => applyPersona(client, persona),
    onError: (error) => refreshPersonaOnConflict(client, error),
  });
}

/**
 * 后端 detail 本来就是中文（"画像已变化，请重新读取后编辑"），比通用文案更准，
 * 所以画像页优先念它自己的话，只有拿不到时才退回通用错误描述。
 */
export function personaErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return '登录已过期，请重新登录';
  if (error instanceof ApiError && error.status === 429) return '改得太快了，这批设置一分钟只能写 10 次，稍等一下再试';
  if (error instanceof ApiError && error.message) return error.message;
  return error instanceof Error ? error.message : '保存失败，请稍后重试';
}
