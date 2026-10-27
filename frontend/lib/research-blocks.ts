export type FundChartBlock = {
  kind: 'chart';
  fundCode: string;
};

export type FundHoldingsBlock = {
  kind: 'holdings';
  fundCode: string;
  reportDate: string;
  items: Array<{ stock_code: string; stock_name: string; weight: number }>;
  warnings: string[];
};

export type ResearchCardBlock =
  | { kind: 'stock'; symbol: string }
  | {
      kind: 'sector';
      sectorCode: string;
      sectorType: 'industry' | 'concept';
    }
  | {
      kind: 'allocation';
      fundCode: string;
      accountId: number | null;
      action: 'build' | 'increase' | 'reduce' | 'exit';
      amount: number;
    };

export type ResearchBlock =
  | { kind: 'text'; content: string }
  | FundChartBlock
  | FundHoldingsBlock
  | ResearchCardBlock;

function parseChart(raw: string): FundChartBlock | null {
  if (raw.length > 8_192) return null;
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (
      Object.keys(data).length === 3 &&
      data.schema_version === 2 &&
      data.type === 'fund_performance' &&
      typeof data.fund_code === 'string' &&
      /^\d{6}$/.test(data.fund_code)
    ) {
      return { kind: 'chart', fundCode: data.fund_code };
    }
  } catch {
    // 不是 JSON 的代码块原样留在正文里。
  }
  return null;
}

function parseHoldings(raw: string): FundHoldingsBlock | null {
  if (raw.length > 16_384) return null;
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (
      data.schema_version !== 1 ||
      data.type !== 'holdings' ||
      data.source !== 'fund_service' ||
      typeof data.fund_code !== 'string' ||
      !/^\d{6}$/.test(data.fund_code) ||
      typeof data.report_date !== 'string' ||
      !Array.isArray(data.items) ||
      !Array.isArray(data.warnings)
    ) {
      return null;
    }
    const items: FundHoldingsBlock['items'] = [];
    for (const entry of data.items) {
      if (!entry || typeof entry !== 'object') return null;
      const item = entry as Record<string, unknown>;
      if (
        typeof item.stock_code !== 'string' ||
        typeof item.stock_name !== 'string' ||
        typeof item.weight !== 'number'
      ) {
        return null;
      }
      items.push({
        stock_code: item.stock_code,
        stock_name: item.stock_name,
        weight: item.weight,
      });
    }
    if (items.length === 0 || items.length > 10) return null;
    return {
      kind: 'holdings',
      fundCode: data.fund_code,
      reportDate: data.report_date,
      items,
      warnings: data.warnings.filter(
        (warning): warning is string => typeof warning === 'string',
      ),
    };
  } catch {
    return null;
  }
}

function parseResearch(raw: string): ResearchCardBlock | null {
  if (raw.length > 2_048) return null;
  try {
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (data.schema_version !== 1) return null;
    if (
      data.type === 'stock_price' &&
      Object.keys(data).length === 3 &&
      typeof data.symbol === 'string' &&
      /^(?:(?:sh|sz|bj)\d{6}|hk\d{5}|us[A-Z][A-Z.]{0,10})$/.test(data.symbol)
    ) {
      return { kind: 'stock', symbol: data.symbol };
    }
    if (
      data.type === 'sector_quote' &&
      Object.keys(data).length === 4 &&
      typeof data.sector_code === 'string' &&
      /^BK\d{4,6}$/.test(data.sector_code) &&
      (data.sector_type === 'industry' || data.sector_type === 'concept')
    ) {
      return {
        kind: 'sector',
        sectorCode: data.sector_code,
        sectorType: data.sector_type,
      };
    }
    if (
      data.type === 'fund_allocation' &&
      Object.keys(data).length === 6 &&
      typeof data.fund_code === 'string' &&
      /^\d{6}$/.test(data.fund_code) &&
      (data.account_id === null ||
        (Number.isSafeInteger(data.account_id) && Number(data.account_id) > 0)) &&
      ['build', 'increase', 'reduce', 'exit'].includes(String(data.action)) &&
      typeof data.amount === 'number' &&
      Number.isFinite(data.amount) &&
      data.amount > 0
    ) {
      return {
        kind: 'allocation',
        fundCode: data.fund_code,
        accountId: data.account_id as number | null,
        action: data.action as 'build' | 'increase' | 'reduce' | 'exit',
        amount: data.amount,
      };
    }
  } catch {
    // ignore malformed JSON
  }
  return null;
}

/**
 * 报告里的结构化块藏在完整围栏内；识别失败就退回普通 markdown，
 * 未闭合的围栏（流式半截）也不会被吞掉。
 */
export function splitResearchBlocks(content: string): ResearchBlock[] {
  const blocks: ResearchBlock[] = [];
  const lines = /[^\n]*(?:\n|$)/g;
  let fence: {
    marker: string;
    length: number;
    start: number;
    body: number;
  } | null = null;
  let cursor = 0;
  let line: RegExpExecArray | null;

  while ((line = lines.exec(content)) && line[0]) {
    const match = /^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?\n?$/.exec(line[0]);
    if (!match) continue;
    const marker = match[1][0];
    if (!fence) {
      fence = {
        marker,
        length: match[1].length,
        start: line.index,
        body: lines.lastIndex,
      };
      continue;
    }
    if (marker !== fence.marker || match[1].length < fence.length) continue;
    const raw = content.slice(fence.body, line.index);
    const parsed = parseChart(raw) ?? parseHoldings(raw) ?? parseResearch(raw);
    if (parsed) {
      if (cursor < fence.start) {
        blocks.push({ kind: 'text', content: content.slice(cursor, fence.start) });
      }
      blocks.push(parsed);
      cursor = lines.lastIndex;
    }
    fence = null;
  }
  if (cursor < content.length) {
    blocks.push({ kind: 'text', content: content.slice(cursor) });
  }
  return blocks;
}
