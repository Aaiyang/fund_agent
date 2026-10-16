/**
 * 选基金面板的纯逻辑：上限、选择顺序、按钮文案与提问正文。
 *
 * 抽出来是为了能像 `utils/researchProgress.ts` 那样在 `node --test` 里直接跑：
 * 上限和"选满后不能再选"这类规则一旦写进组件就很难验证。
 */

export const MAX_PICKER_FUNDS = 3;

/** 成本档位：single 一次模型出报告；multi_role 三角色合议，token 是前者的数倍。 */
export type ResearchTier = 'single' | 'multi_role';

export type PickerFund = { code: string; name: string };

/** 发给后端的一对参数：研究对象代码 + 成本档位。 */
export type ClientResearch = { codes: string[]; strategy: ResearchTier };

/**
 * 按基金代码去重，保留首次出现的顺序。
 *
 * `/portfolio/positions` 不带 account_id 时是"每(账户,基金)一行"，同一只基金
 * 开在两个账户里就会重复出现：面板上既是两行相同名字，React key 也撞车，
 * 点掉一行另一行又把它加回来，看起来就像"取消点几次就不管用"。
 */
export function dedupePickerFunds<T extends PickerFund>(rows: T[]): T[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    if (seen.has(row.code)) return false;
    seen.add(row.code);
    return true;
  });
}

export type HoldingRow = { daily_return?: number | null; daily_profit_loss?: number | null };

/**
 * 同一只基金跨账户的面板口径：收益率取净值日涨幅（各账户同源、数值一致），
 * 收益金额按账户合计。取第一条非空的收益率，而不是把各账户的百分比相加。
 */
export function summarizeHoldings(rows: HoldingRow[]): { rate: number | null; profit: number | null; accounts: number } {
  const rates = rows.map((row) => row.daily_return).filter((value): value is number => value != null);
  const profits = rows.map((row) => row.daily_profit_loss).filter((value): value is number => value != null);
  return {
    rate: rates.length ? rates[0] : null,
    profit: profits.length ? profits.reduce((total, value) => total + value, 0) : null,
    accounts: rows.length,
  };
}

/** 已选按点选顺序保留（对比报告里第一只是主对象），重复点选则取消。 */
export function togglePickerFund(selected: PickerFund[], fund: PickerFund): PickerFund[] {
  if (selected.some((item) => item.code === fund.code)) {
    return selected.filter((item) => item.code !== fund.code);
  }
  if (selected.length >= MAX_PICKER_FUNDS) return selected;
  return [...selected, fund];
}

export function pickerRowDisabled(selected: PickerFund[], code: string): boolean {
  return selected.length >= MAX_PICKER_FUNDS && !selected.some((item) => item.code === code);
}

/** 一只就是"分析"，两只以上才是"对比"：文案要跟着后端会走的意图变。 */
export function pickerActionLabel(count: number): string {
  return count > 1 ? '对比分析' : '分析';
}

export function pickerHint(count: number): string {
  if (count === 0) return `最多可选${MAX_PICKER_FUNDS}只`;
  const left = MAX_PICKER_FUNDS - count;
  return left > 0 ? `已选 ${count} 只，还可选 ${left} 只` : `已选 ${count} 只，已达上限`;
}

/**
 * 报告下方那个多角色入口的文案（也是发出去的指令原文）。
 *
 * 以前一律写"请对这份报告进行多角色深度研究"——措辞不对：服务端做的是把**这份报告的
 * 研究对象**用多角色深跑一遍，报告本身既不是输入也不是被审对象。文案要说清对象是谁，
 * 所以按 intent 分档；对比类必须写成"对比"，否则用户以为只研究了第一只。
 */
export function researchFollowupLabel(intent: string | null | undefined): string {
  switch (intent) {
    case 'fund_comparison':
      return '对这几只基金做多角色深度对比';
    case 'portfolio_diagnosis':
      return '对我的组合做多角色深度诊断';
    case 'allocation_analysis':
      return '对这笔操作做多角色深度情景分析';
    case 'fund_research':
      return '对这只基金做多角色深度研究';
    default:
      return '做多角色深度研究';
  }
}

/**
 * 正文只给人看，研究对象和成本档位走 `research_fund_codes` / `research_strategy`。
 *
 * 不能靠这句话被后端的文本规则猜回去：基金名里常带"股票/行业/主题"，
 * 那些词会让规则路径直接放弃（见 utils/task_routing.py 的排除项）。
 */
export function composeResearchQuestion(selected: PickerFund[]): string {
  const label = selected.map((item) => (item.name ? `${item.code} ${item.name}` : item.code)).join('、');
  return selected.length > 1 ? `请对比这几只基金：${label}` : `请分析这只基金：${label}`;
}
