import { Stack, router } from 'expo-router';
import { useState } from 'react';
import { Text } from 'react-native';

import { Button, Card, Field, Screen, SectionTitle } from '@/components/ui';
import { describeError } from '@/components/states';
import { theme } from '@/constants/theme';
import { useAuthStore } from '@/stores/auth';
import { formatDateTime } from '@/utils/format';

/** 编辑当前登录用户自己的资料（spec 3.1）。 */
export default function ProfileEditScreen() {
  const user = useAuthStore((state) => state.user);
  const updateProfile = useAuthStore((state) => state.updateProfile);
  const [username, setUsername] = useState(user?.username ?? '');
  const [email, setEmail] = useState(user?.email ?? '');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit() {
    setProblem(null);
    const nextUsername = username.trim();
    const nextEmail = email.trim();
    if (!nextEmail) {
      setProblem('请输入邮箱');
      return;
    }
    // 只提交改过的字段：接口把省略未传的字段理解为“保持原值”。
    const payload: { username?: string; email?: string } = {};
    if (nextUsername !== (user?.username ?? '')) payload.username = nextUsername;
    if (nextEmail !== (user?.email ?? '')) payload.email = nextEmail;
    if (Object.keys(payload).length === 0) {
      setProblem('没有需要保存的修改');
      return;
    }
    setBusy(true);
    try {
      await updateProfile(payload);
      router.back();
    } catch (error) {
      setProblem(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <Stack.Screen options={{ title: '编辑资料' }} />
      <Card>
        <SectionTitle title="用户信息" />
        <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 12 }}>
          用户 #{user?.id} · 注册于 {formatDateTime(user?.created_at)}
        </Text>
        <Field label="昵称" value={username} onChangeText={setUsername} placeholder="请输入昵称" />
        <Field label="邮箱" value={email} onChangeText={setEmail} keyboardType="email-address" placeholder="请输入邮箱" />
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
        <Button label="保存" onPress={submit} loading={busy} />
      </Card>
    </Screen>
  );
}
