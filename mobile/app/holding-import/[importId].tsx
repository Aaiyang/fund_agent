import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { PurchaseDateField, purchaseDateProblem } from '@/components/PurchaseDateFields';
import { Async, LoadingState, describeError } from '@/components/states';
import { Badge, Button, Card, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useConfirmImport, useDeleteImport, useImportDetail, useUpdateImportItem, type ImportItem } from '@/hooks/useImports';
import { formatMoney, toInputNumber } from '@/utils/format';

const ISSUE_LABEL: Record<string, string> = {
  fund_unresolved: '未匹配到基金',
  missing_market_value_and_shares: '缺少金额与份额',
  low_confidence: '匹配置信度低',
  market_value_suspiciously_large: '金额异常偏大',
  profit_loss_inconsistent_with_value: '收益与金额不匹配',
  profit_loss_rate_out_of_range: '收益率超出范围',
  duplicate_fund_different_values: '同一基金金额冲突',
};

/** Review + confirm an import batch. Nothing is written until confirm (spec 3.7). */
export default function ImportReviewScreen() {
  const { importId } = useLocalSearchParams<{ importId: string }>();
  const detail = useImportDetail(importId ?? null);
  const updateItem = useUpdateImportItem();
  const confirm = useConfirmImport(importId ?? null);
  const remove = useDeleteImport();
  const [result, setResult] = useState<string | null>(null);

  return (
    <Screen>
      <Async query={detail}>
        {(batch) => {
          if (batch.status === 'UPLOADED' || batch.status === 'PARSING') {
            return (
              <Card>
                <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>正在识别截图…</Text>
                <LoadingState />
              </Card>
            );
          }

          return (
            <>
              <Card>
                <SectionTitle
                  title={`${batch.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'} · ${statusLabel(batch.status)}`}
                />
                <Text style={{ fontSize: 12, color: theme.textMuted }}>
                  账户 #{batch.account_id} · 识别 {batch.items_detected} 条 · 图片 {batch.image_count} 张
                  {batch.source_app ? ` · 来源 ${batch.source_app}` : ''}
                </Text>
                {batch.error_message ? (
                  <Text style={{ fontSize: 12, color: theme.danger, marginTop: 6 }}>{batch.error_message}</Text>
                ) : null}
              </Card>

              {(batch.items ?? []).map((item) => (
                <ItemCard key={item.id} item={item} importId={importId} updateItem={updateItem} />
              ))}

              {batch.status === 'REVIEW_REQUIRED' ? (
                <Card>
                  <Button
                    label={`确认导入 ${
                      // Mirrors confirm_import's rule: an error row defaults to
                      // SKIP, and an unmatched row can never be applied.
                      (batch.items ?? []).filter(
                        (item) =>
                          !!item.matched_fund_code &&
                          (item.user_action ?? (item.validation_status === 'error' ? 'SKIP' : 'UPDATE')) === 'UPDATE',
                      ).length
                    } 条`}
                    loading={confirm.isPending}
                    onPress={() =>
                      confirm.mutate(undefined, {
                        onSuccess: (data) =>
                          setResult(`已写入 ${data.applied} 条持仓，跳过 ${data.skipped} 条。原图已删除。`),
                        onError: (error) => setResult(`确认失败：${describeError(error)}`),
                      })
                    }
                  />
                  <View style={{ marginTop: 10 }}>
                    <Button
                      label="取消并删除该批次"
                      variant="danger"
                      onPress={() =>
                        remove.mutate(importId, {
                          onSuccess: () => router.back(),
                          onError: (error) => setResult(`删除失败：${describeError(error)}`),
                        })
                      }
                    />
                  </View>
                  {result ? <Text style={{ fontSize: 13, color: theme.primary, marginTop: 10 }}>{result}</Text> : null}
                  <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 10 }}>
                    确认后按“覆盖当前快照”写入，并记一条 IMPORT_ADJUSTMENT 审计记录；系统不会据此推断买卖流水。
                  </Text>
                </Card>
              ) : null}

              {batch.status === 'APPLIED' ? (
                <Card>
                  <Text style={{ fontSize: 13, color: theme.text }}>
                    该批次已于导入 {batch.items_confirmed} 条持仓后生效，可返回“持有”页查看。
                  </Text>
                  <Button label="返回持有" onPress={() => router.replace('/(tabs)')} />
                </Card>
              ) : null}
            </>
          );
        }}
      </Async>
    </Screen>
  );
}

function ItemCard({
  item,
  importId,
  updateItem,
}: {
  item: ImportItem;
  importId: string;
  updateItem: ReturnType<typeof useUpdateImportItem>;
}) {
  const [marketValue, setMarketValue] = useState(toInputNumber(item.market_value));
  const [purchaseDate, setPurchaseDate] = useState(item.purchase_date ?? '');
  const [problem, setProblem] = useState<string | null>(null);
  const skipped = (item.user_action ?? (item.validation_status === 'error' ? 'SKIP' : 'UPDATE')) === 'SKIP';

  return (
    <Card style={{ opacity: skipped ? 0.55 : 1 }}>
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>
        {item.matched_fund_name ?? item.raw_fund_name ?? '未识别基金'}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
        {item.matched_fund_code ?? '无代码'} · 置信度 {typeof item.confidence === 'number' ? `${Math.round(item.confidence * 100)}%` : '--'}
      </Text>
      {(item.validation_issues ?? []).length > 0 ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
          {(item.validation_issues ?? []).map((issue) => (
            <View key={issue} style={{ marginRight: 6, marginBottom: 6 }}>
              <Badge label={ISSUE_LABEL[issue] ?? issue} tone={item.validation_status === 'error' ? 'danger' : 'warning'} />
            </View>
          ))}
        </View>
      ) : null}

      <View style={{ flexDirection: 'row', marginTop: 10 }}>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 12, color: theme.textFaint }}>当前持仓</Text>
          <Text style={{ fontSize: 14, color: theme.text }}>{formatMoney(item.current_market_value)}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 12, color: theme.textFaint }}>本次识别</Text>
          <Text style={{ fontSize: 14, color: theme.text }}>{formatMoney(item.market_value)}</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={{ fontSize: 12, color: theme.textFaint }}>导入后</Text>
          <Text style={{ fontSize: 14, color: theme.primary }}>{formatMoney(skipped ? item.current_market_value : item.market_value)}</Text>
        </View>
      </View>

      <Field
        label="修正持有金额"
        value={marketValue}
        onChangeText={setMarketValue}
        keyboardType="numeric"
        placeholder="请输入修正后的持有金额"
      />
      <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 8 }}>
        截图里没有买入日期，默认按导入当天记；知道实际日期的话改这里，持有天数从这天算。
      </Text>
      <PurchaseDateField value={purchaseDate} onChangeText={setPurchaseDate} />
      <View style={{ flexDirection: 'row' }}>
        <View style={{ flex: 1, marginRight: 6 }}>
          <Button
            label="保存修正"
            variant="secondary"
            loading={updateItem.isPending}
            onPress={() => {
              const dateProblem = purchaseDateProblem(purchaseDate);
              if (dateProblem) {
                setProblem(dateProblem);
                return;
              }
              setProblem(null);
              updateItem.mutate(
                {
                  importId,
                  itemId: item.id,
                  market_value: marketValue.trim() === '' ? null : Number(marketValue),
                  purchase_date: purchaseDate.trim() || null,
                },
                { onError: (error) => setProblem(describeError(error)) },
              );
            }}
          />
        </View>
        <View style={{ flex: 1, marginLeft: 6 }}>
          <Button
            label={skipped ? '改为导入' : '跳过这条'}
            variant={skipped ? 'primary' : 'secondary'}
            loading={updateItem.isPending}
            onPress={() => {
              setProblem(null);
              updateItem.mutate(
                { importId, itemId: item.id, user_action: skipped ? 'UPDATE' : 'SKIP' },
                { onError: (error) => setProblem(describeError(error)) },
              );
            }}
          />
        </View>
      </View>
      {problem ? <Text style={{ fontSize: 12, color: theme.danger, marginTop: 8 }}>{problem}</Text> : null}
    </Card>
  );
}

function statusLabel(status: string): string {
  return (
    {
      UPLOADED: '已上传',
      PARSING: '识别中',
      REVIEW_REQUIRED: '待确认',
      CONFIRMED: '已确认',
      APPLIED: '已导入',
      PARSE_FAILED: '识别失败',
      CANCELLED: '已取消',
    }[status] ?? status
  );
}
