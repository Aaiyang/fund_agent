import { router } from 'expo-router';
import { Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Button, Card, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useImportHistory } from '@/hooks/useImports';

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '识别中',
  REVIEW_REQUIRED: '待确认',
  CONFIRMED: '已确认',
  APPLIED: '已导入',
  PARSE_FAILED: '识别失败',
  CANCELLED: '已取消',
};

/** Import entry: choose manual entry or screenshot recognition (spec 3.7). */
export default function HoldingImportScreen() {
  const history = useImportHistory();

  return (
    <Screen>
      <Card>
        <SectionTitle title="导入持仓" />
        <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20, marginBottom: 12 }}>
          导入是“当前持仓快照”的覆盖更新，系统不会根据截图推断你的买卖流水。任何结果都要经你确认后才会写入正式持仓。
        </Text>
        <Button label="手动录入" onPress={() => router.push('/holding-import/manual')} />
        <View style={{ marginTop: 10 }}>
          <Button label="上传持仓截图识别" variant="secondary" onPress={() => router.push('/holding-import/screenshots')} />
        </View>
      </Card>

      <Card>
        <SectionTitle title="导入记录" />
        <Async
          query={history}
          empty={(data) => (data.items.length === 0 ? <EmptyState title="暂无导入记录" /> : null)}
        >
          {(data) => (
            <>
              {data.items.map((item) => (
                <Card key={item.id} style={{ marginBottom: 8, borderWidth: 1, borderColor: theme.border }}>
                  <SectionTitle
                    title={`${item.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'} · ${STATUS_LABEL[item.status] ?? item.status}`}
                    action="查看"
                    onAction={() => router.push(`/holding-import/${item.id}`)}
                  />
                  <Text style={{ fontSize: 12, color: theme.textMuted }}>
                    账户 #{item.account_id} · 识别 {item.items_detected} 条 · 确认 {item.items_confirmed} 条 ·{' '}
                    {new Date(item.created_at ?? '').toLocaleString()}
                  </Text>
                  {item.error_message ? (
                    <Text style={{ fontSize: 12, color: theme.danger, marginTop: 4 }}>{item.error_message}</Text>
                  ) : null}
                </Card>
              ))}
            </>
          )}
        </Async>
      </Card>
    </Screen>
  );
}
