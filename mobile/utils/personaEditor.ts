import type { PersonaFieldKey, PersonaFields } from '@/hooks/useUserPersona';
export const PERSONA_GROUPS = {
    investment: {
        title: '投资偏好', caption: '经验、风险偏好与基金类型',
        fields: ['investment_experience', 'risk_preference', 'excluded_fund_types'],
    },
    goals: {
        title: '目标与期限', caption: '希望实现什么，计划持有多久',
        fields: ['investment_goals', 'investment_horizon_months'],
    },
    assistant: {
        title: '回答习惯', caption: '让回答更符合你的阅读习惯',
        fields: ['response_language', 'response_detail'],
    },
} as const;
export type PersonaGroup = keyof typeof PERSONA_GROUPS;
export function countPersonaFields(fields: PersonaFields): number {
    return Object.values(PERSONA_GROUPS).flatMap((group) => group.fields)
        .filter((key) => fields[key] != null && (!Array.isArray(fields[key]) || fields[key].length > 0)).length;
}
/** 仅提交当前分组的真实变化；未设置不填默认值，清除使用显式 null。 */
export function buildPersonaChanges(group: PersonaGroup, original: PersonaFields, draft: PersonaFields, horizon: string, pendingGoal: string): PersonaFields {
    const values = { ...draft };
    if (group === 'goals') {
        const months = horizon.trim();
        if (months && (!/^\d+$/.test(months) || Number(months) < 1 || Number(months) > 600)) {
            throw new Error('请输入 1–600 之间的整数月份，或留空表示暂未确定。');
        }
        values.investment_horizon_months = months ? Number(months) : null;
        const goals = [...(draft.investment_goals ?? []), ...(pendingGoal.trim() ? [pendingGoal] : [])].map((goal) => goal.trim());
        if (goals.some((goal) => !goal || goal.length > 120))
            throw new Error('每个目标需填写 1–120 个字。');
        if (goals.length > 5)
            throw new Error('最多保留 5 个投资目标，请先移除一项。');
        if (new Set(goals).size !== goals.length)
            throw new Error('目标重复了，请修改或移除重复内容。');
        values.investment_goals = goals.length ? goals : null;
    }
    if (group === 'investment' && values.excluded_fund_types?.length === 0)
        values.excluded_fund_types = null;
    const changes: PersonaFields = {};
    for (const key of PERSONA_GROUPS[group].fields as readonly PersonaFieldKey[]) {
        if (JSON.stringify(original[key] ?? null) !== JSON.stringify(values[key] ?? null)) {
            Object.assign(changes, { [key]: values[key] ?? null });
        }
    }
    return changes;
}
