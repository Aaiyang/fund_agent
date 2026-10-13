/**
 * 改持仓 / 下单时对照用的基金信息条。
 *
 * 代码是从基金详情页带进来的，不是让用户在这里重填的 —— 换成名称、代码、最新
 * 净值与日期、涨跌幅，他报金额和成本价时手边就有参照，也不会把一只基金的修改
 * 保存到另一只上去。
 */

import { Text, View } from 'react-native';

import { theme } from '@/constants/theme';
import { formatDate, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

export function FundReference({
  code,
  name,
  nav,
  navDate,
  dailyReturn,
  note,
}: {
  code: string;
  name: string | null | undefined;
  nav: number | null | undefined;
  navDate: string | null | undefined;
  dailyReturn: number | null | undefined;
  note?: string;
}) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ fontSize: 15, fontWeight: '700', color: theme.text }} numberOfLines={2}>
        {name || code}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 4 }}>
        {code} · 最新净值 {formatNumber(nav, 4)}（{formatDate(navDate)}）·{' '}
        <Text style={{ color: trendColor(dailyReturn), fontWeight: '600' }}>{formatReturnPoints(dailyReturn)}</Text>
      </Text>
      {note ? (
        <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 4 }}>{note}</Text>
      ) : null}
    </View>
  );
}
