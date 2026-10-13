import { Link, Stack } from 'expo-router';
import { Text, View } from 'react-native';

import { theme } from '@/constants/theme';

export default function NotFoundScreen() {
  return (
    <>
      <Stack.Screen options={{ title: '页面不存在', headerBackVisible: false }} />
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 20, backgroundColor: theme.background }}>
        <Text style={{ fontSize: 17, fontWeight: '600', color: theme.text }}>没有找到这个页面</Text>
        <Text style={{ fontSize: 12, color: theme.textMuted, marginTop: 6 }}>链接可能过期或地址输错了</Text>
        <Link
          href="/"
          accessibilityRole="link"
          style={{ marginTop: 8, paddingVertical: 8, paddingHorizontal: 10, color: theme.primary, fontSize: 15 }}
        >
          回首页
        </Link>
      </View>
    </>
  );
}
