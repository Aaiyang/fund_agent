import type { ChatResearchProgress } from '@/api/chatStream';

const STAGES = { evidence: '收集研究证据', analysis: '独立分析', review: '交叉审核', supplement: '补充证据', revision: '反馈修订', report: '综合报告' };
// 与后端 app/agent/roles.py 的 ROLE_OWNERS 同源：进度那一行说的是"谁在忙"，不是"哪块数据"。
// 维度名（业绩与基准契合…）由服务端写在报告正文与尾注里，这里再写一遍只会挤掉一行空间。
// 用 Record 而不是收窄的联合类型，是为了让后端新增维度时界面退化成显示原始 key，
// 而不是渲染出 undefined。
const ROLES: Record<string, string> = {
  performance: '业绩分析师',
  risk: '风险分析师',
  holdings: '持仓与风格分析师',
  manager: '基金经理研究员',
  disclosure: '披露与来源质量审查员',
  portfolio: '组合配置顾问',
};
const STATUS = { started: '进行中', completed: '已完成', partial: '有待确认项', failed: '未完成', skipped: '无需执行' };
/** 后端加了新维度而这里还没配中文名时，退化成显示原始 key，而不是渲染出 undefined。 */
const roleLabel = (role: string) => ROLES[role] ?? role;
const STAGE_ORDER = ['evidence', 'analysis', 'review', 'supplement', 'revision', 'report'];

/** Stage callbacks can arrive in any role order; retain each role without mixing runs. */
export function mergeResearchProgress(previous: ChatResearchProgress[], next: ChatResearchProgress): ChatResearchProgress[] {
  if (previous.length && previous[0].run_id !== next.run_id) return previous;
  const existing = previous.find((item) => item.stage === next.stage && item.role === next.role);
  if (existing && existing.status !== 'started') return previous;
  return [...previous.filter((item) => item.stage !== next.stage || item.role !== next.role), next];
}

export function describeResearchProgress(events: ChatResearchProgress[]): string | undefined {
  const latest = events.reduce<ChatResearchProgress | undefined>((current, event) => (
    !current || STAGE_ORDER.indexOf(event.stage) >= STAGE_ORDER.indexOf(current.stage) ? event : current
  ), undefined);
  if (!latest) return undefined;
  const active = events.filter((item) => item.stage === latest.stage && item.status !== 'skipped');
  if (!active.length) return `${STAGES[latest.stage]}：无需执行`;
  // 归属人和状态之间要有分隔：以前直连会拼出"风险分析师已完成"，读起来像一个人名叫这个。
  return `${STAGES[latest.stage]}：${active
    .map((item) => [item.role ? roleLabel(item.role) : '', STATUS[item.status]].filter(Boolean).join(' · '))
    .join(' · ')}`;
}

/** 一行滚动摘要：角色名 + 服务端截好的思考尾部（已经是单行）。 */
export function describeResearchActivity(activity: { role: string | null; text: string }): string {
  const role = activity.role ? roleLabel(activity.role) : '';
  return `${role}${role ? ' · ' : ''}${activity.text}`;
}

/** 一个角色的最终结局。`skipped` 是"这个角色本轮不需要做"，不算失败。 */
export type RoleOutcome = {
  role: string;
  status: 'completed' | 'partial' | 'failed' | 'skipped';
};

/**
 * 从进度事件里取每个角色的结局：修订轮覆盖首轮，进行中的角色不算结局。
 *
 * 界面在流式过程中也要能报数，所以这里从进度帧推；报告落库后改用服务端
 * 随消息一起返回的 `research_roles`（同一份信封数据，刷新后不丢）。
 */
export function roleOutcomesFromProgress(events: ChatResearchProgress[]): RoleOutcome[] {
  const outcomes = new Map<RoleOutcome['role'], RoleOutcome>();
  for (const item of events) {
    if (!item.role || item.stage !== 'analysis' && item.stage !== 'revision') continue;
    if (item.status === 'started') continue;
    outcomes.set(item.role, { role: item.role, status: item.status });
  }
  return [...outcomes.values()];
}

/**
 * 一行徽标文案：数字来自服务端信封，不来自模型在正文里的自述。
 *
 * 分母只算"这轮真该出结论的角色"——`skipped`（没有个人持仓时的组合适配）既不算
 * 失败，也不占进"N 个角色"里，否则一句"3 个角色里 2 个失败"会把本来就不适用的那
 * 一个也算成没失败的幸存者。
 */
export function describeRoleOutcomes(outcomes: RoleOutcome[], reviewStatus?: string | null): string | undefined {
  if (!outcomes.length) return undefined;
  const skipped = outcomes.filter((item) => item.status === 'skipped').length;
  const attempted = outcomes.filter((item) => item.status !== 'skipped');
  const tail: string[] = [];
  if (skipped) tail.push(attempted.length ? `${skipped} 个无需执行` : `${skipped} 个角色本轮无需执行`);
  if (reviewStatus === 'failed') tail.push('交叉审核未完成');
  else if (reviewStatus === 'partial') tail.push('交叉审核有待确认项');
  if (!attempted.length) return tail.join(' · ');
  const failed = attempted.filter((item) => item.status === 'failed').length;
  const partial = attempted.filter((item) => item.status === 'partial').length;
  const head = failed
    ? `${attempted.length} 个角色里 ${failed} 个失败`
    : partial
      ? `${attempted.length} 个角色里 ${partial} 个有待确认项`
      : `${attempted.length} 个角色已完成`;
  return [head, ...tail].join(' · ');
}
