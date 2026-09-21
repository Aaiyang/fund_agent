import { useLocalSearchParams } from 'expo-router';
import { Text } from 'react-native';

import { Card, Screen } from '@/components/ui';
import { theme } from '@/constants/theme';

/**
 * Agent placeholder (spec 4.1). Phase 1 ships no agent capability: the page
 * shows the roadmap and, when entered from a fund detail page, the fund code
 * context it will eventually use.
 */
export default function AgentScreen() {
  const { fund_code: fundCode } = useLocalSearchParams<{ fund_code?: string }>();

  return (
    <Screen>
      <Card>
        <Text style={{ fontSize: 19, fontWeight: '700', color: theme.text }}>AI 基金助手</Text>
        <Text style={{ fontSize: 14, color: theme.textMuted, marginTop: 6 }}>Agent 功能开发中</Text>
        <Text style={{ fontSize: 13, color: theme.textMuted, marginTop: 16, lineHeight: 22 }}>
          后续将支持：{'\n'}· 分析我的持仓{'\n'}· 查看我的自选{'\n'}· 分析指定基金{'\n'}· 基金对比
        </Text>
      </Card>
      {fundCode ? (
        <Card>
          <Text style={{ fontSize: 13, color: theme.textMuted }}>已携带上下文</Text>
          <Text style={{ fontSize: 15, color: theme.text, marginTop: 4, fontWeight: '600' }}>基金代码 {fundCode}</Text>
          <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 8 }}>
            第一阶段不会基于该代码执行推理，也不会给出投资建议。
          </Text>
        </Card>
      ) : null}
    </Screen>
  );
}
