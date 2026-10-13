/** 单行基金条目，自选、搜索结果、持仓列表与导入记录共用一种排版。 */

import { Link } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { Badge } from '@/components/ui';
import { theme } from '@/constants/theme';
import { formatDate, formatDateTime, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

export type FundRowAction = { label: string; tone?: 'primary' | 'danger' | 'muted'; onPress: () => void };

export function FundRow({
  fundCode,
  fundName,
  latestNav,
  dailyReturn,
  navDate,
  extra,
  badges = [],
  action,
  pending,
  fullDate = false,
}: {
  fundCode: string;
  fundName: string;
  latestNav: number | null | undefined;
  dailyReturn: number | null | undefined;
  navDate?: string | null;
  /** 名称下方的辅助行（账户、成本、分组名等）。 */
  extra?: string;
  badges?: { label: string; tone?: 'warning' | 'danger' | 'muted' }[];
  /**
   * 行内按钮渲染在链接的*旁边*、绝不嵌进链接里：web 上内部的可交互元素
   * 拦不住外层 <a> 跳转。
   */
  action?: FundRowAction;
  /** 该按钮的请求在途时把它调暗。 */
  pending?: boolean;
  /** 审计/变更记录这类要看时刻的列表用完整日期时间，普通列表只给日期。 */
  fullDate?: boolean;
}) {
  return (
    <View
      style={{
        flexDirection: 'row',
        alignItems: 'center',
        borderBottomWidth: 1,
        borderBottomColor: theme.border,
      }}
    >
      <Link href={{ pathname: '/fund/[code]', params: { code: fundCode } }} asChild>
        <Pressable
          accessibilityRole="link"
          accessibilityLabel={`查看 ${fundName} 详情`}
          style={{ flex: 1, paddingVertical: 12, paddingRight: 8 }}
        >
          <Text style={{ fontSize: 15, color: theme.text, fontWeight: '500' }} numberOfLines={1}>
            {fundName}
          </Text>
          <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
            {fundCode}
            {navDate ? ` · ${fullDate ? formatDateTime(navDate) : formatDate(navDate)}` : ''}
            {extra ? ` · ${extra}` : ''}
          </Text>
          {badges.length > 0 ? (
            <View style={{ flexDirection: 'row', marginTop: 6, flexWrap: 'wrap' }}>
              {badges.map((badge) => (
                <View key={badge.label} style={{ marginRight: 6 }}>
                  <Badge label={badge.label} tone={badge.tone ?? 'muted'} />
                </View>
              ))}
            </View>
          ) : null}
        </Pressable>
      </Link>
      <View style={{ alignItems: 'flex-end', paddingLeft: 8 }}>
        <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>{formatNumber(latestNav)}</Text>
        <Text style={{ fontSize: 13, color: trendColor(dailyReturn ?? 0), marginTop: 2 }}>
          {formatReturnPoints(dailyReturn)}
        </Text>
        {action ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`${action.label} ${fundName}`}
            hitSlop={10}
            onPress={action.onPress}
            style={({ pressed }) => [{ marginTop: 6, opacity: pending ? 0.5 : pressed ? 0.7 : 1 }]}
          >
            <Text
              style={{
                fontSize: 12,
                color:
                  action.tone === 'danger'
                    ? theme.danger
                    : action.tone === 'muted'
                      ? theme.textFaint
                      : theme.primary,
              }}
            >
              {action.label}
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}
