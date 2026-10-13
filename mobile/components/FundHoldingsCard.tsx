import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';

import { type FundHoldingsCard as HoldingsData } from '../../shared/fund-holdings';
import { theme } from '@/constants/theme';
import { formatPoints } from '@/utils/format';

export function FundHoldingsCard({ holdings }: { holdings: HoldingsData }) {
  const [expanded, setExpanded] = useState(false);
  const items = expanded ? holdings.items : holdings.items.slice(0, 6);
  return (
    <View style={{ backgroundColor: theme.surface, borderRadius: 16, borderWidth: 1, borderColor: theme.border, padding: 14, gap: 8 }}>
      <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text }}>重仓股票占比</Text>
      <Text style={{ fontSize: 12, color: theme.textMuted }}>{holdings.fund_code} · 披露期 {holdings.report_date}</Text>
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
        {items.map((item) => (
          <View key={item.stock_code} style={{ width: '30%', flexGrow: 1, minWidth: 78, padding: 10, borderRadius: 8, backgroundColor: theme.background, gap: 6 }}>
            <Text style={{ fontSize: 14, fontWeight: '500', color: theme.text }}>{item.stock_name}</Text>
            <Text style={{ fontSize: 11, color: theme.textMuted }}>{item.stock_code}</Text>
            <Text style={{ fontSize: 12, color: theme.primary }}>占净值 {formatPoints(item.weight)}</Text>
          </View>
        ))}
      </View>
      {holdings.items.length > 6 ? (
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel={expanded ? '收起重仓股票' : `查看全部 ${holdings.items.length} 只重仓股票`}
          hitSlop={8}
          onPress={() => setExpanded(!expanded)}
          style={({ pressed }) => [{ minHeight: 44, justifyContent: 'center', opacity: pressed ? 0.85 : 1 }]}
        >
          <Text style={{ fontSize: 14, color: theme.primary }}>{expanded ? '收起' : '查看全部'}重仓股票（{holdings.items.length} 只）</Text>
        </Pressable>
      ) : null}
      <Text style={{ fontSize: 11, lineHeight: 17, color: theme.textMuted }}>来源：基金数据服务 · 定期披露，非实时持仓；披露权重不能直接作为涨跌贡献。</Text>
      {holdings.warnings.map((warning, index) => (
        <Text key={index} style={{ fontSize: 12, lineHeight: 18, color: theme.warning }}>{warning}</Text>
      ))}
    </View>
  );
}
