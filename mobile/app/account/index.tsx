import { router } from 'expo-router';
import { Alert, Text, View } from 'react-native';

import { Async, EmptyState } from '@/components/states';
import { Button, Card, Screen, SectionTitle } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAccounts, useDeleteAccount } from '@/hooks/usePortfolio';
import { useUiStore } from '@/stores/ui';
import { formatDateTime } from '@/utils/format';

/** Account management: create, switch, rename, delete (spec 3.6). */
export default function AccountListScreen() {
  const accounts = useAccounts();
  const setAccountId = useUiStore((state) => state.setAccountId);
  const remove = useDeleteAccount();

  return (
    <Screen>
      <Card>
        <SectionTitle title="持仓账户" action="添加账户" onAction={() => router.push('/account/add')} />
        <Async
          query={accounts}
          empty={(data) => (data.items.length === 0 ? <EmptyState title="还没有账户" hint="先创建一个账户，再录入或导入持仓" /> : null)}
        >
          {(data) => (
            <View>
              {data.items.map((account) => (
                <View key={account.id} style={{ paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: theme.border }}>
                  <Text style={{ fontSize: 15, color: theme.text, fontWeight: '600' }}>{account.name}</Text>
                  <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 2 }}>
                    来源标签 {account.source_app ?? '未标注'} · 导入方式 {account.import_mode} · 最近导入{' '}
                    {formatDateTime(account.last_imported_at)}
                  </Text>
                  <View style={{ flexDirection: 'row', marginTop: 10 }}>
                    <View style={{ flex: 1, marginRight: 6 }}>
                      <Button
                        label="设为当前视图"
                        variant="secondary"
                        onPress={() => {
                          setAccountId(account.id);
                          router.push('/(tabs)');
                        }}
                      />
                    </View>
                    <View style={{ flex: 1, marginRight: 6 }}>
                      <Button label="改名" variant="secondary" onPress={() => router.push(`/account/${account.id}`)} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Button
                        label="删除"
                        variant="danger"
                        onPress={() =>
                          Alert.alert(
                            '删除账户',
                            `“${account.name}”的持仓、调整记录与导入批次都会一并删除，且无法恢复。`,
                            [
                              { text: '取消', style: 'cancel' },
                              { text: '确认删除', style: 'destructive', onPress: () => remove.mutate(account.id) },
                            ],
                          )
                        }
                      />
                    </View>
                  </View>
                </View>
              ))}
            </View>
          )}
        </Async>
      </Card>
    </Screen>
  );
}
