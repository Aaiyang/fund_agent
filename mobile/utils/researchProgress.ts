import type { ChatResearchProgress } from '@/api/chatStream';

const STAGES = { evidence: '收集研究证据', analysis: '独立分析', review: '交叉审核', supplement: '补充证据', revision: '反馈修订', report: '综合报告' };
const ROLES = { fundamentals: '基金研究员', risk: '风险分析员', portfolio: '组合分析员' };
const STATUS = { started: '进行中', completed: '已完成', partial: '有待确认项', failed: '未完成', skipped: '无需执行' };
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
  return `${STAGES[latest.stage]}：${active.map((item) => `${item.role ? ROLES[item.role] : ''}${STATUS[item.status]}`).join(' · ')}`;
}
