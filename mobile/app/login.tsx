import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, Text, View } from 'react-native';

import { ApiError } from '@/api/client';
import { Button, Card, Field } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useAuthStore } from '@/stores/auth';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** 密码规则与后端校验器（app/schemas/auth.py）保持一致。 */
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
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: theme.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      {/* 宽屏（web）垂直居中，不然下半屏空着一大片；手机上仍从顶部排，
          因为键盘弹起时居中会把品牌挤出可视区。 */}
      <View
        style={{
          flex: 1,
          padding: 16,
          justifyContent: Platform.OS === 'web' ? 'center' : 'flex-start',
        }}
      >
        <View style={{ width: '100%', maxWidth: 400, alignSelf: 'center' }}>
          {/* 品牌第一屏：App 叫「持见」，聊天助手「小镜」只是其中一个功能，别混用。 */}
          <View style={{ alignItems: 'center', marginTop: 24, marginBottom: 22 }}>
            <View
              style={{
                width: 46,
                height: 46,
                borderRadius: 13,
                backgroundColor: theme.primary,
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: 12,
              }}
            >
              <Text style={{ fontSize: 21, fontWeight: '700', color: '#FFFFFF' }}>持</Text>
            </View>
            <Text style={{ fontSize: 22, fontWeight: '700', color: theme.text }}>持见</Text>
            <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 5 }}>个人基金管理</Text>
          </View>

          <Card>
            <Text style={{ fontSize: 19, fontWeight: '700', color: theme.text, marginBottom: 4 }}>
              {mode === 'login' ? '登录' : '注册新账号'}
            </Text>
            <Text style={{ fontSize: 13, color: theme.textMuted, marginBottom: 18 }}>
              {mode === 'login' ? '使用邮箱与密码登录' : '注册后自动登录，数据仅保存在本实例数据库'}
            </Text>
            <Field label="邮箱" value={email} onChangeText={setEmail} keyboardType="email-address" placeholder="请输入邮箱" />
            <Field
              label="密码"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              placeholder="请输入密码"
              labelExtra={
                // 规则只在注册时提醒：登录只是把原来的密码输回来，摆着规则反而像在让它改密码。
                mode === 'register' ? (
                  <Text style={{ fontSize: 11, color: theme.textFaint, flex: 1, textAlign: 'right' }}>
                    至少 8 位，含大小写、数字与符号
                  </Text>
                ) : undefined
              }
            />
            {mode === 'register' ? <Field label="昵称" value={username} onChangeText={setUsername} placeholder="选填" /> : null}
            {problem ? (
              <View
                style={{
                  backgroundColor: 'rgba(185, 28, 28, 0.06)',
                  borderRadius: 8,
                  paddingHorizontal: 10,
                  paddingVertical: 9,
                  marginBottom: 12,
                }}
              >
                <Text style={{ color: theme.danger, fontSize: 13 }}>{problem}</Text>
              </View>
            ) : null}
            <Button label={mode === 'login' ? '登录' : '注册并登录'} onPress={submit} loading={busy} />
          </Card>

          {/* 切换注册/登录是次要动作，做成一行文字链；之前是整条描边按钮，
              和「登录」那颗抢视觉重量。 */}
          <View style={{ flexDirection: 'row', justifyContent: 'center', alignItems: 'center' }}>
            <Text style={{ fontSize: 13, color: theme.textMuted }}>{mode === 'login' ? '还没有账号？' : '已有账号？'}</Text>
            <Pressable
              accessibilityRole="button"
              hitSlop={10}
              onPress={() => {
                setMode(mode === 'login' ? 'register' : 'login');
                setProblem(null);
              }}
              style={{ paddingVertical: 8, paddingHorizontal: 4 }}
            >
              <Text style={{ fontSize: 13, color: theme.primary, fontWeight: '600' }}>
                {mode === 'login' ? '去注册' : '去登录'}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
