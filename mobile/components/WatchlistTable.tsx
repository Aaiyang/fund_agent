/**
 * 自选表格：共用 {@link DataTable} 布局，列是自选自己的指标（spec 3.3）。
 */

import { DataTable, type DataColumn } from '@/components/DataTable';
import { theme } from '@/constants/theme';
import type { WatchlistFund } from '@/hooks/useWatchlist';
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
    title: '当日涨跌',
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

export function WatchlistTable({
  items,
  onRemove,
  pendingCode,
}: {
  items: WatchlistFund[];
  onRemove: (fundCode: string) => void;
  pendingCode?: string;
}) {
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
      columns={COLUMNS}
      action={{
        title: '操作',
        busy: (item) => pendingCode === item.fund_code,
        label: (item) => (pendingCode === item.fund_code ? '删除中' : '删除'),
        onPress: (item) => onRemove(item.fund_code),
      }}
    />
  );
}
