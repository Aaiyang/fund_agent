/**
 * Holdings grid: the same {@link DataTable} layout as 自选, with the derived
 * holding metrics (占比/收益) as horizontally scrollable columns.
 */

import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import type { PositionItem } from '@/hooks/usePortfolio';
import { formatDate, formatMoney, formatNumber, formatRate, formatReturnPoints, formatSignedMoney, trendColor } from '@/utils/format';

const COLUMNS: DataColumn<PositionItem>[] = [
  { key: 'value', title: '持有金额', width: 92, cell: (item) => ({ text: formatMoney(item.market_value) }) },
  { key: 'ratio', title: '占比', width: 68, cell: (item) => ({ text: formatRate(item.position_ratio) }) },
  {
    key: 'daily',
    title: '当日涨跌',
    width: 84,
    cell: (item) => ({
      text: formatReturnPoints(item.daily_return),
      color: trendColor(item.daily_return),
      sub: formatDate(item.nav_date),
      subColor: item.is_updated ? theme.textFaint : theme.warning,
    }),
  },
  {
    key: 'dailyProfit',
    title: '昨日收益',
    width: 88,
    cell: (item) => ({ text: formatSignedMoney(item.daily_profit_loss), color: trendColor(item.daily_profit_loss) }),
  },
  {
    key: 'profit',
    title: '累计收益',
    width: 92,
    cell: (item) => ({ text: formatSignedMoney(item.profit_loss), color: trendColor(item.profit_loss) }),
  },
  {
    key: 'profitRate',
    title: '收益率',
    width: 76,
    cell: (item) => ({ text: formatRate(item.profit_loss_rate), color: trendColor(item.profit_loss_rate) }),
  },
  { key: 'shares', title: '持仓份额', width: 84, cell: (item) => ({ text: formatNumber(item.shares) }) },
  { key: 'costNav', title: '成本净值', width: 80, cell: (item) => ({ text: formatNumber(item.average_cost_nav) }) },
  {
    key: 'days',
    title: '持有天数',
    width: 76,
    cell: (item) => ({ text: item.holding_days === null || item.holding_days === undefined ? '--' : `${item.holding_days} 天` }),
  },
];

export function HoldingsTable({ items, accountNames }: { items: PositionItem[]; accountNames: Record<number, string> }) {
  return (
    <DataTable
      items={items}
      padded={false}
      scrollRows={false}
      keyOf={(item) => `${item.account_id}-${item.fund_code}`}
      fundCodeOf={(item) => item.fund_code}
      nameOf={(item) => ({
        title: item.fund_name ?? item.fund_code,
        sub: [item.fund_code, accountNames[item.account_id] ?? `账户 #${item.account_id}`].join(' · '),
      })}
      columns={COLUMNS}
      hint="左右滑动查看其它列 · 占比与收益由后端在查询时计算，不落库"
    />
  );
}
