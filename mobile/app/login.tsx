import { router } from 'expo-router';
import { useState } from 'react';
import { Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { Button, Card, Field } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAuthStore } from '@/stores/auth';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Password rules mirror the backend validator (app/schemas/auth.py). */
function passwordProblem(password: string): string | null {
  if (password.length < 8) return '密码至少 8 位';
  if (!/[A-Z]/.test(password)) return '密码需包含大写字母';
  if (!/[a-z]/.test(password)) return '密码需包含小写字母';
  if (!/[0-9]/.test(password)) return '密码需包含数字';
  if (!/[!@#$%^&*(),.?":{}|<>]/.test(password)) return '密码需包含特殊字符';
  return null;
}

export default function LoginScreen() {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [username, setUsername] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const signIn = useAuthStore((state) => state.signIn);
  const signUp = useAuthStore((state) => state.signUp);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setProblem(null);
    if (!EMAIL.test(email)) {
      setProblem('请输入有效邮箱');
      return;
    }
    if (mode === 'register') {
      const invalid = passwordProblem(password);
      if (invalid) {
        setProblem(invalid);
        return;
      }
    }
    setBusy(true);
    try {
      if (mode === 'login') await signIn(email.trim(), password);
      else await signUp(email.trim(), password, username.trim() || undefined);
      router.replace('/(tabs)');
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : '网络异常，请稍后重试');
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={{ flex: 1, backgroundColor: theme.background, padding: 16 }}>
      <Card>
        <Text style={{ fontSize: 20, fontWeight: '700', color: theme.text, marginBottom: 4 }}>
          {mode === 'login' ? '登录 Fund Agent' : '注册新账号'}
        </Text>
        <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 16 }}>
          {mode === 'login' ? '使用邮箱与密码登录' : '注册后自动登录，数据仅保存在本实例数据库'}
        </Text>
        <Field label="邮箱" value={email} onChangeText={setEmail} keyboardType="email-address" placeholder="you@example.com" />
        <Field label="密码" value={password} onChangeText={setPassword} secureTextEntry placeholder="至少 8 位，含大小写、数字与符号" />
        {mode === 'register' ? (
          <Field label="昵称（可选）" value={username} onChangeText={setUsername} placeholder="用于 Agent 称呼你" />
        ) : null}
        {problem ? <Text style={{ color: theme.danger, fontSize: 13, marginBottom: 12 }}>{problem}</Text> : null}
        <Button label={mode === 'login' ? '登录' : '注册并登录'} onPress={submit} loading={busy} />
        <View style={{ marginTop: 10 }}>
          <Button
            label={mode === 'login' ? '还没有账号？去注册' : '已有账号？去登录'}
            variant="secondary"
            onPress={() => {
              setMode(mode === 'login' ? 'register' : 'login');
              setProblem(null);
            }}
          />
        </View>
      </Card>
    </View>
  );
}
