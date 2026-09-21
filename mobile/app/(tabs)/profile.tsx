import { router } from 'expo-router';
import { Alert, Text, View } from 'react-native';

import { Async } from '@/components/states';
import { Button, Card, Screen, SectionTitle } from '@/components/ui';
import { FundRow } from '@/components/FundRow';
import { theme } from '@/constants/theme';
import { useImportHistory } from '@/hooks/useImports';
import { useAuthStore } from '@/stores/auth';
import { formatDateTime } from '@/utils/format';

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '识别中',
  REVIEW_REQUIRED: '待确认',
  CONFIRMED: '已确认',
  APPLIED: '已导入',
  PARSE_FAILED: '识别失败',
  CANCELLED: '已取消',
};

export default function ProfileScreen() {
  const user = useAuthStore((state) => state.user);
  const signOut = useAuthStore((state) => state.signOut);
  const history = useImportHistory();

  function confirmSignOut() {
    Alert.alert('退出登录', '退出后需要重新登录，且此前签发的刷新令牌会失效。', [
      { text: '取消', style: 'cancel' },
      { text: '退出', style: 'destructive', onPress: () => void signOut().then(() => router.replace('/login')) },
    ]);
  }

  return (
    <Screen>
      <Card>
        <Text style={{ fontSize: 17, fontWeight: '700', color: theme.text }}>{user?.username ?? '未设置昵称'}</Text>
        <Text style={{ fontSize: 13, color: theme.textMuted, marginTop: 2 }}>{user?.email}</Text>
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
          用户 #{user?.id} · 注册于 {formatDateTime(user?.created_at)}
        </Text>
      </Card>

      <Card>
        <SectionTitle title="持仓与账户" />
        <MenuLink label="账户管理" hint="新增、改名、删除账户" onPress={() => router.push('/account')} />
        <MenuLink label="交易 / 调整记录" hint="查看导入与手工修正审计" onPress={() => router.push('/transactions')} />
        <MenuLink label="导入持仓" hint="手动录入或截图识别" onPress={() => router.push('/holding-import')} />
      </Card>

      <Card>
        <SectionTitle title="自选" />
        <MenuLink label="自选分组管理" hint="新建、改名、删除、组内排序" onPress={() => router.push('/watchlist-groups')} />
      </Card>

      <Card>
        <SectionTitle title="导入记录" action="发起新导入" onAction={() => router.push('/holding-import')} />
        <Async
          query={history}
          empty={(data) => (data.items.length === 0 ? <Text style={{ color: theme.textFaint, fontSize: 13 }}>暂无导入记录</Text> : null)}
        >
          {(data) => (
            <View>
              {data.items.map((item) => (
                <FundRow
                  key={item.id}
                  fundCode={item.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'}
                  fundName={`${STATUS_LABEL[item.status] ?? item.status} · 账户 #${item.account_id}`}
                  latestNav={item.items_detected}
                  dailyReturn={null}
                  navDate={item.created_at}
                  extra={`确认 ${item.items_confirmed} 条${item.error_message ? ` · ${item.error_message}` : ''}`}
                  action={{ label: '查看', onPress: () => router.push(`/holding-import/${item.id}`) }}
                />
              ))}
            </View>
          )}
        </Async>
      </Card>

      <Card>
        <Button label="退出登录" variant="danger" onPress={confirmSignOut} />
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 10 }}>
          持仓截图只作为临时文件用于识别，确认或取消后由后端删除，不写入数据库。
        </Text>
      </Card>
    </Screen>
  );
}

function MenuLink({ label, hint, onPress }: { label: string; hint: string; onPress: () => void }) {
  return (
    <View style={{ paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: theme.border }}>
      <Text style={{ fontSize: 15, color: theme.text, fontWeight: '500' }} onPress={onPress}>
        {label}
      </Text>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }} onPress={onPress}>
        {hint}
      </Text>
    </View>
  );
}
