/**
 * 持仓截图的人工复核卡片。
 *
 * 这是整条链路里唯一能写持仓的地方：Agent 的工具只负责把草稿查出来并暂停等待，
 * 聊天里说"确认"不算数，必须走 `POST /chatbot/holding-imports/{id}/decision`。
 * 卡片上的说明文案（`notice`）用服务端给的那句，不在前端另写一套口径——它说的是
 * "按基金覆盖快照、截图里没有的不会删"，写错了会误导人删持仓。
 */

import { ScrollView, Text, View } from 'react-native';

import type { components } from '@/api/schema';
import { Badge, Button, Card } from '@/components/ui';
import { theme } from '@/constants/theme';
import { formatMoney, formatSignedMoney } from '@/utils/format';

type Review = components['schemas']['HoldingImportReview'];
type Item = components['schemas']['ImportItemOut'];

function ItemRow({ item }: { item: Item }) {
  const name = item.matched_fund_name ?? item.raw_fund_name ?? '（没认出来的行）';
  const issues = item.validation_issues ?? [];
  const blocked = item.validation_status === 'error' || Boolean(item.matched_fund_code) === false;
  const skipped = item.user_action === 'SKIP' || (blocked && !item.user_action);
  return (
    <View style={{ paddingVertical: 8, borderTopWidth: 1, borderColor: theme.border }}>
      <View style={{ flexDirection: 'row', alignItems: 'center' }}>
        <Text style={{ flex: 1, fontSize: 14, color: theme.text }} numberOfLines={1}>
          {name}
        </Text>
        {issues.length ? <Badge label={`校验 ${issues.length} 项`} tone={blocked ? 'danger' : 'warning'} /> : null}
      </View>
      <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 2 }}>
        {item.matched_fund_code ? `${item.matched_fund_code} · ` : '没匹配到代码 · '}
        金额 {formatMoney(item.market_value)} · 收益 {formatSignedMoney(item.profit_loss)}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 2 }}>
        份额 {item.shares ?? '未识别'} · 置信度 {item.confidence == null ? '未知' : `${Math.round(item.confidence * 100)}%`}
        {skipped ? ' · 该行将跳过' : ''}
      </Text>
      {item.current_market_value != null ? (
        <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 2 }}>当前持仓金额 {formatMoney(item.current_market_value)}</Text>
      ) : null}
      {issues.length ? (
        <Text style={{ fontSize: 12, color: blocked ? theme.danger : theme.warning, marginTop: 2 }} numberOfLines={2}>
          {issues.join('；')}
        </Text>
      ) : null}
    </View>
  );
}

export function ImportReviewCard({
  review,
  pending,
  onDecide,
}: {
  review: Review;
  pending: 'confirm' | 'cancel' | null;
  onDecide: (decision: 'confirm' | 'cancel') => void;
}) {
  const items = review.items ?? [];
  const problemCount = items.filter((item) => (item.validation_issues ?? []).length > 0).length;

  return (
    <Card>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        <Text style={{ flex: 1, fontSize: 15, fontWeight: '600', color: theme.text }}>持仓截图识别结果 · 等你确认</Text>
        <Badge label="人工复核" tone="muted" />
      </View>
      <Text style={{ fontSize: 12, color: theme.textMuted, lineHeight: 18 }}>{review.notice}</Text>
      <Text style={{ fontSize: 13, color: theme.text, marginTop: 6 }}>目标账户：{review.account_name || `账户 ${review.account_id}`}</Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 6 }}>
        {review.image_count} 张图 · 识别出 {items.length} 行
        {problemCount ? ` · ${problemCount} 行有校验问题` : ''}
      </Text>

      <ScrollView style={{ maxHeight: 260 }} nestedScrollEnabled>
        {items.map((item) => (
          <ItemRow key={item.id} item={item} />
        ))}
      </ScrollView>

      <View style={{ flexDirection: 'row', marginTop: 12 }}>
        <View style={{ flex: 1, marginRight: 8 }}>
          <Button label="取消这次导入" variant="secondary" disabled={pending !== null} loading={pending === 'cancel'} onPress={() => onDecide('cancel')} />
        </View>
        <View style={{ flex: 1 }}>
          <Button label="确认应用" disabled={pending !== null} loading={pending === 'confirm'} onPress={() => onDecide('confirm')} />
        </View>
      </View>
      <Text style={{ fontSize: 11, color: theme.textFaint, marginTop: 8, lineHeight: 16 }}>
        确认会覆盖该账户的持仓快照并写入调整流水；这一步只有点按钮有效，在对话里回复「确认」不会改账本。
      </Text>
    </Card>
  );
}
