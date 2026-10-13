import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Text, View } from 'react-native';

import { Async, LoadingState, describeError } from '@/components/states';
import { Badge, Button, Card, Chip, Field, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useConfirmImport, useDeleteImport, useImportDetail, useUpdateImportItem, type ImportItem } from '@/hooks/useImports';
import { formatMoney, formatReturnPoints, formatSignedMoney, toInputNumber } from '@/utils/format';

const ISSUE_LABEL: Record<string, string> = {
  fund_unresolved: '未匹配到基金',
  missing_market_value_and_shares: '缺少金额与份额',
  low_confidence: '匹配置信度低',
  market_value_suspiciously_large: '金额异常偏大',
  profit_loss_inconsistent_with_value: '收益与金额不匹配',
  profit_loss_rate_out_of_range: '收益率超出范围',
  duplicate_fund_different_values: '同一基金金额冲突',
  fund_name_truncated: '名称被截断',
  profit_and_rate_disagree: '收益与收益率一正一负',
};

/** 审阅并确认一个导入批次。用户点击确认之前不会写入任何数据（spec 3.7）。 */
export default function ImportReviewScreen() {
  const { importId } = useLocalSearchParams<{ importId: string }>();
  const detail = useImportDetail(importId ?? null);
  const updateItem = useUpdateImportItem();
  const confirm = useConfirmImport(importId ?? null);
  const remove = useDeleteImport();
  const [result, setResult] = useState<string | null>(null);

  // 底部就是确认按钮，且每张卡片都带一个修正金额的输入框。
  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
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
                  </Text>
                  {batch.error_message ? (
                    <Text style={{ fontSize: 12, color: theme.danger, marginTop: 6 }}>{batch.error_message}</Text>
                  ) : null}
                </Card>

                {(batch.items ?? []).map((item) => (
                  <ItemCard
                    key={item.id}
                    item={item}
                    importId={importId}
                    updateItem={updateItem}
                    editable={batch.status === 'REVIEW_REQUIRED'}
                  />
                ))}

                {batch.status === 'REVIEW_REQUIRED' ? (
                  <Card>
                    <Button
                      label={`确认导入 ${
                        // 与后端 confirm_import 的口径一致：校验出错的行默认按 SKIP，
                        // 未匹配到基金的行永远不可能被写入。
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
                        loading={remove.isPending}
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
                      该批次已导入 {batch.items_confirmed} 条持仓并生效，可返回“持有”页查看。
                    </Text>
                    <Button label="返回持有" onPress={() => router.replace('/(tabs)')} />
                  </Card>
                ) : null}
              </>
            );
          }}
        </Async>
      </Screen>
    </KeyboardAvoidingView>
  );
}

function ItemCard({
  item,
  importId,
  updateItem,
  editable,
}: {
  item: ImportItem;
  importId: string;
  updateItem: ReturnType<typeof useUpdateImportItem>;
  editable: boolean;
}) {
  const [marketValue, setMarketValue] = useState(toInputNumber(item.market_value));
  const [problem, setProblem] = useState<string | null>(null);
  const skipped = (item.user_action ?? (item.validation_status === 'error' ? 'SKIP' : 'UPDATE')) === 'SKIP';
  // 一次只改一行：整份列表共用 isPending 会让每张卡片同时显示“处理中…”。
  const pendingHere = updateItem.isPending && updateItem.variables?.itemId === item.id;
  const savingValue = pendingHere && updateItem.variables?.user_action === undefined;
  const savingAction = pendingHere && updateItem.variables?.user_action !== undefined;

  function pick(fundCode: string) {
    setProblem(null);
    updateItem.mutate(
      { importId, itemId: item.id, fund_code: fundCode },
      { onError: (error) => setProblem(describeError(error)) },
    );
  }

  const header = (
    <>
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>
        {item.matched_fund_name ?? item.raw_fund_name ?? '未识别基金'}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
        {item.matched_fund_code ?? '无代码'} · 置信度 {typeof item.confidence === 'number' ? `${Math.round(item.confidence * 100)}%` : '--'}
        {/* 标题显示的是基金自身的名称；这里拼的是截图上打印的原始文字，
            保留它是为了不用离开页面就能核对模糊匹配的结果。 */}
        {item.matched_fund_name && item.raw_fund_name && item.matched_fund_name !== item.raw_fund_name
          ? ` · 截图 ${item.raw_fund_name}`
          : ''}
      </Text>
    </>
  );

  // 批次一旦生效，服务端会拒绝任何后续修改，卡片就不再假装还能编辑：
  // 只展示已写入的内容，编辑控件一概不给。
  if (!editable) {
    return (
      <Card>
        {header}
        <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 8 }}>
          持有金额 {formatMoney(item.market_value)} · 持有收益 {formatSignedMoney(item.profit_loss)} · 持有收益率{' '}
          {formatReturnPoints(item.profit_loss_rate)}
        </Text>
      </Card>
    );
  }

  return (
    <Card style={{ opacity: skipped ? 0.55 : 1 }}>
      {header}
      {(item.validation_issues ?? []).length > 0 ? (
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8 }}>
          {(item.validation_issues ?? []).map((issue) => (
            <View key={issue} style={{ marginRight: 6, marginBottom: 6 }}>
              <Badge label={ISSUE_LABEL[issue] ?? issue} tone={item.validation_status === 'error' ? 'danger' : 'warning'} />
            </View>
          ))}
        </View>
      ) : null}

      {/* 截图上很少印出基金代码，而同一个名称往往同时覆盖同一只基金的 A/C 份额——
          用户持有的到底是哪一类只有他自己知道，所以这里列出候选让他挑，
          而不是替他猜。 */}
      {!item.matched_fund_code && (item.candidates ?? []).length > 0 ? (
        <View style={{ marginTop: 8 }}>
          <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 6 }}>选一只</Text>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
            {(item.candidates ?? []).map((candidate) => (
              <Chip
                key={candidate.fund_code}
                label={`${candidate.fund_code} ${candidate.fund_name ?? ''}`}
                onPress={() => pick(candidate.fund_code ?? '')}
              />
            ))}
          </View>
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

      {/* 截图右侧那一列本来就是持有收益和它的收益率。两个都展示出来，
          识别出错在这里就能看出来——收益率是导入流程唯一不落库的数字
          （之后按 成本 = 金额 − 收益 反推），所以它与应用算出的数不一致时，
          说明是真实的差异，而不是字段丢了。 */}
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 8 }}>
        持有收益 {formatSignedMoney(item.profit_loss)} · 持有收益率 {formatReturnPoints(item.profit_loss_rate)}
      </Text>

      <Field
        label="修正持有金额"
        value={marketValue}
        onChangeText={setMarketValue}
        keyboardType="numeric"
        placeholder="请输入修正后的持有金额"
      />
      <View style={{ flexDirection: 'row' }}>
        <View style={{ flex: 1, marginRight: 6 }}>
          <Button
            label="保存修正"
            variant="secondary"
            loading={savingValue}
            onPress={() => {
              setProblem(null);
              if (marketValue.trim() !== '' && Number.isNaN(Number(marketValue))) {
                setProblem('修正持有金额需为数字');
                return;
              }
              updateItem.mutate(
                {
                  importId,
                  itemId: item.id,
                  market_value: marketValue.trim() === '' ? null : Number(marketValue),
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
            loading={savingAction}
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
