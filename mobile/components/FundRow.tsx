/** One fund line item, shared by watchlist, search results and holdings. */

import { Link } from 'expo-router';
import { Pressable, Text, View } from 'react-native';

import { Badge } from '@/components/ui';
import { theme } from '@/constants/theme';
import { formatDate, formatNumber, formatReturnPoints, trendColor } from '@/utils/format';

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
}: {
  fundCode: string;
  fundName: string;
  latestNav: number | null | undefined;
  dailyReturn: number | null | undefined;
  navDate?: string | null;
  /** Secondary line under the name (account, cost, group names…). */
  extra?: string;
  badges?: { label: string; tone?: 'warning' | 'danger' | 'muted' }[];
  /**
   * Row button rendered *beside* the link, never inside it: on web an
   * interactive child cannot stop the surrounding anchor from navigating.
   */
  action?: FundRowAction;
  /** Dim the action while its request is in flight. */
  pending?: boolean;
}) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: theme.border }}>
      <Link href={{ pathname: '/fund/[code]', params: { code: fundCode } }} asChild>
        <Pressable accessibilityRole="link" style={{ flex: 1, paddingVertical: 12, paddingRight: 8 }}>
          <Text style={{ fontSize: 15, color: theme.text, fontWeight: '500' }} numberOfLines={1}>
            {fundName}
          </Text>
          <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
            {fundCode}
            {navDate ? ` · ${formatDate(navDate)}` : ''}
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
            style={{ marginTop: 6, opacity: pending ? 0.5 : 1 }}
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
