/**
 * 自选表格：共用 {@link DataTable} 布局，列是自选自己的指标（spec 3.3）。
 */

import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import type { WatchlistFund } from '@/hooks/useWatchlist';
import { estimateHint, type FundEstimate } from '@/hooks/useValuation';
import { formatDate, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

/** 滚动窗口收益列的公共工厂，近1周/近1月/近3月/近6月/近1年共用。 */
function periodColumn(key: string, title: string, pick: (item: WatchlistFund) => number | null | undefined): DataColumn<WatchlistFund> {
  return {
    key,
    title,
    width: 76,
    sortValue: pick,
    cell: (item) => ({ text: formatReturnPoints(pick(item)), color: trendColor(pick(item)) }),
  };
}

const COLUMNS: DataColumn<WatchlistFund>[] = [
  { key: 'nav', title: '最新净值', width: 80, sortValue: (item) => item.latest_nav, cell: (item) => ({ text: formatNumber(item.latest_nav) }) },
  {
    key: 'daily',
    // 叫「最新涨幅」而不是「当日涨跌」：净值可能来自更早的交易日（下面那行副文本
    // 就是它的净值日期），与持仓表同一说法，两屏口径才对得上。
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
  // 给盘中估值留的位置：数据源还没有估值接口，这列就在表里占住位、
  // 如实标注未接入。
  { key: 'estimate', title: '预估涨幅', width: 84, cell: () => ({ text: '--', sub: '未接入' }) },
  periodColumn('weekly', '近1周', (item) => item.weekly_return),
  periodColumn('monthly', '近1月', (item) => item.monthly_return),
  periodColumn('quarterly', '近3月', (item) => item.quarterly_return),
  periodColumn('semiannual', '近6月', (item) => item.semiannual_return),
  periodColumn('annual', '近1年', (item) => item.annual_return),
];

/**
 * 预估涨幅列：有数按涨跌上色，没数要说清是哪一种「没有」.
 *
 * 与持仓表那一列同一套判据：QDII 的空白是口径决定，不是接口坏了。
 */
function estimateColumn(estimates: Record<string, FundEstimate>): DataColumn<WatchlistFund> {
  return {
    key: 'estimate',
    title: '预估涨幅',
    width: 84,
    sortValue: (item) => estimates[item.fund_code]?.change_pct,
    cell: (item) => {
      const estimate = estimates[item.fund_code];
      const value = estimate?.available ? estimate.change_pct : null;
      return {
        text: formatReturnPoints(value),
        color: trendColor(value),
        sub: estimate?.available ? formatDate(estimate.quote_date) : estimateHint(estimate),
        subColor: theme.textFaint,
      };
    },
  };
}

export function WatchlistTable({
  items,
  onRemove,
  pendingCode,
  estimates = {},
}: {
  items: WatchlistFund[];
  onRemove: (fundCode: string) => void;
  pendingCode?: string;
  estimates?: Record<string, FundEstimate>;
}) {
  // 占位列留在原位（读不到估值时它才是对的），拿到结果后按 key 换成实时那一列。
  const columns = COLUMNS.map((column) => (column.key === 'estimate' ? estimateColumn(estimates) : column));

  return (
    <DataTable
      items={items}
      style={{ flex: 1 }}
      keyOf={(item) => item.fund_code}
      hrefOf={(item) => ({ pathname: '/fund/[code]', params: { code: item.fund_code } })}
      nameOf={(item) => ({
        title: item.fund_name,
        sub: [
          item.fund_code,
          item.is_held ? '持有' : '',
          (item.groups ?? []).length > 0 ? (item.groups ?? []).join('/') : '',
        ]
          .filter(Boolean)
          .join(' · '),
      })}
      columns={columns}
      action={{
        title: '操作',
        busy: (item) => pendingCode === item.fund_code,
        label: (item) => (pendingCode === item.fund_code ? '删除中' : '删除'),
        onPress: (item) => onRemove(item.fund_code),
      }}
    />
  );
}
