/**
 * Holdings grid: the same {@link DataTable} layout as 自选, with the derived
 * holding metrics (占比/收益) as horizontally scrollable columns. The holding
 * amount stays in the fixed name column so it never scrolls out of view.
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
      hint="点表头排序（再点切换升/降） · 左右滑动查看其它列 · 占比与收益由后端在查询时计算，不落库"
    />
  );
}
