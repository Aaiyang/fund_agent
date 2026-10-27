import { request } from '@/lib/api';

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
};

export type PersonaProposal = {
  id: string;
  base_revision: number;
  changes: PersonaFields;
  evidence: string;
  status: string;
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
  changes: Record<string, unknown>;
  source: string;
  created_at: string;
};

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

export const EXPERIENCE_LEVELS = ['beginner', 'intermediate', 'experienced'] as const;
export const RISK_LEVELS = ['conservative', 'balanced', 'aggressive'] as const;
export const RESPONSE_LANGUAGES = ['zh-CN', 'en'] as const;
export const RESPONSE_DETAILS = ['concise', 'balanced', 'detailed'] as const;
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

export const PERSONA_GROUPS = {
  investment: {
    title: '投资偏好',
    caption: '经验、风险偏好与基金类型',
    fields: ['investment_experience', 'risk_preference', 'excluded_fund_types'],
  },
  goals: {
    title: '目标与期限',
    caption: '希望实现什么，计划持有多久',
    fields: ['investment_goals', 'investment_horizon_months'],
  },
  assistant: {
    title: '回答习惯',
    caption: '让回答更符合你的阅读习惯',
    fields: ['response_language', 'response_detail'],
  },
} as const;

export type PersonaGroup = keyof typeof PERSONA_GROUPS;

export function formatOptionLabel(key: PersonaFieldKey, value: string): string {
  if (key === 'excluded_fund_types')
    return FUND_TYPE_LABELS[value as FundType] ?? value;
  if (key === 'risk_preference' && value === 'balanced') return '平衡';
  return OPTION_LABELS[value] ?? value;
}

export function formatFieldValue(
  key: PersonaFieldKey,
  value: PersonaFields[PersonaFieldKey],
): string {
  if (value === null || value === undefined) return '未设置';
  if (key === 'investment_horizon_months') return `${String(value)} 个月`;
  if (Array.isArray(value)) {
    if (value.length === 0) return '无';
    return value
      .map((item) => formatOptionLabel(key, String(item)))
      .join('、');
  }
  return formatOptionLabel(key, String(value));
}

export function describeChanges(changes: Record<string, unknown>): string {
  const entries = Object.entries(changes ?? {}) as Array<
    [PersonaFieldKey, PersonaFields[PersonaFieldKey]]
  >;
  return entries.length
    ? entries
        .map(([key, value]) => `${FIELD_LABELS[key] ?? key}：${formatFieldValue(key, value)}`)
        .join('；')
    : '（没有字段变化）';
}

export function sourceLabel(source?: string): string {
  if (source === 'user_edit') return '我自己填的';
  if (source === 'user_confirmed_proposal') return '确认过 Agent 的提议';
  return source || '来源未知';
}

export function countPersonaFields(fields: PersonaFields): number {
  return Object.values(PERSONA_GROUPS)
    .flatMap((group) => group.fields)
    .filter(
      (key) =>
        fields[key] != null &&
        (!Array.isArray(fields[key]) || fields[key].length > 0),
    ).length;
}

export async function getUserPersona(token: string): Promise<Persona> {
  const data = await request<Persona>('/agent/user-profile', {}, token);
  return {
    revision: data.revision ?? 0,
    fields: data.fields ?? {},
    provenance: data.provenance ?? {},
    pending_proposals: data.pending_proposals ?? [],
  };
}

export async function getPersonaHistory(
  token: string,
  limit = 20,
): Promise<PersonaHistory[]> {
  return request<PersonaHistory[]>(
    `/agent/user-profile/history?limit=${limit}`,
    {},
    token,
  );
}

export async function updatePersona(
  token: string,
  revision: number,
  changes: PersonaFields,
): Promise<Persona> {
  return request<Persona>(
    '/agent/user-profile',
    {
      method: 'PATCH',
      body: JSON.stringify({ changes, expected_revision: revision }),
    },
    token,
  );
}

export async function decidePersonaProposal(
  token: string,
  revision: number,
  proposalId: string,
  decision: 'accept' | 'reject',
): Promise<Persona> {
  return request<Persona>(
    `/agent/user-profile/proposals/${proposalId}/decision`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, expected_revision: revision }),
    },
    token,
  );
}

export async function clearPersona(
  token: string,
  revision: number,
): Promise<Persona> {
  return request<Persona>(
    '/agent/user-profile',
    {
      method: 'DELETE',
      body: JSON.stringify({ expected_revision: revision }),
    },
    token,
  );
}
