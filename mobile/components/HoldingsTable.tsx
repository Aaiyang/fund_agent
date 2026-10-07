/**
 * 持仓表格：和自选用同一套 {@link DataTable} 布局，派生的持仓指标
 * （占比/收益）做成可横向滚动的列。持有金额留在固定的名称列里，
 * 永远不会被滚出视野。
 */

import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import type { PositionItem } from '@/hooks/usePortfolio';
import { formatDate, formatMoney, formatNumber, formatRate, formatReturnPoints, formatSignedMoney, trendColor } from '@/utils/format';

const COLUMNS: DataColumn<PositionItem>[] = [
  { key: 'nav', title: '最新净值', width: 80, sortValue: (item) => item.unit_nav, cell: (item) => ({ text: formatNumber(item.unit_nav) }) },
  { key: 'ratio', title: '持仓占比', width: 84, sortValue: (item) => item.position_ratio, cell: (item) => ({ text: formatRate(item.position_ratio) }) },
  {
    key: 'daily',
    title: '最新涨幅',
    width: 84,
    sortValue: (item) => item.daily_return,
    cell: (item) => ({
      text: formatReturnPoints(item.daily_return),
      color: trendColor(item.daily_return),
      sub: formatDate(item.nav_date),
      subColor: item.is_updated ? theme.textFaint : theme.warning,
    }),
  },
  // 与自选那边同款预留列：盘中估值还没有后端来源，这列就在最新涨幅
  // 旁边占住位置，并注明未接入。
  { key: 'estimate', title: '预估涨幅', width: 84, cell: () => ({ text: '--', sub: '未接入' }) },
  {
    key: 'weeklyProfit',
    title: '本周收益',
    width: 88,
    sortValue: (item) => item.weekly_profit_loss,
    cell: (item) => ({ text: formatSignedMoney(item.weekly_profit_loss), color: trendColor(item.weekly_profit_loss) }),
  },
  {
    key: 'monthlyProfit',
    title: '本月收益',
    width: 88,
    sortValue: (item) => item.monthly_profit_loss,
    cell: (item) => ({ text: formatSignedMoney(item.monthly_profit_loss), color: trendColor(item.monthly_profit_loss) }),
  },
  {
    key: 'dailyProfit',
    title: '昨日收益',
    width: 88,
    sortValue: (item) => item.daily_profit_loss,
    cell: (item) => ({ text: formatSignedMoney(item.daily_profit_loss), color: trendColor(item.daily_profit_loss) }),
  },
  {
    key: 'profit',
    title: '累计收益',
    width: 92,
    sortValue: (item) => item.profit_loss,
    cell: (item) => ({ text: formatSignedMoney(item.profit_loss), color: trendColor(item.profit_loss) }),
  },
  {
    key: 'profitRate',
    title: '收益率',
    width: 76,
    sortValue: (item) => item.profit_loss_rate,
    cell: (item) => ({ text: formatRate(item.profit_loss_rate), color: trendColor(item.profit_loss_rate) }),
  },
  { key: 'shares', title: '持仓份额', width: 84, sortValue: (item) => item.shares, cell: (item) => ({ text: formatNumber(item.shares) }) },
  { key: 'costNav', title: '成本净值', width: 80, sortValue: (item) => item.average_cost_nav, cell: (item) => ({ text: formatNumber(item.average_cost_nav) }) },
  {
    key: 'days',
    title: '持有天数',
    width: 76,
    sortValue: (item) => item.holding_days,
    cell: (item) => ({ text: item.holding_days === null || item.holding_days === undefined ? '--' : `${item.holding_days} 天` }),
  },
];

export function HoldingsTable({ items }: { items: PositionItem[] }) {
  return (
    <DataTable
      items={items}
      padded={false}
      scrollRows={false}
      keyOf={(item) => `${item.account_id}-${item.fund_code}`}
      hrefOf={(item) => ({ pathname: '/fund/[code]', params: { code: item.fund_code } })}
      nameOf={(item) => ({
        title: item.fund_name ?? item.fund_code,
        sub: `${item.fund_code} · ${formatMoney(item.market_value)}`,
      })}
      columns={COLUMNS}
    />
  );
}
