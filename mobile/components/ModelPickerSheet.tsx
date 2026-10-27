/**
 * 聊天页的模型切换面板。
 *
 * 只做「选当前档案」这一件事：列出来自 /agent/llm/profiles 的档案，
 * 点一下调用 /agent/llm/switch。真正的增删改仍在模型设置页，
 * 所以这里底部只留一个入口，不复制整套表单。
 */

import { SymbolView } from 'expo-symbols';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { describeError } from '@/components/states';
import { Button } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useLlmProfiles, useSwitchLlmProfile } from '@/hooks/useLlmProfiles';

export function ModelPickerSheet({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const profiles = useLlmProfiles();
  const switchProfile = useSwitchLlmProfile();
  const [problem, setProblem] = useState<string | null>(null);
  const activeName = profiles.data?.active;
  const items = profiles.data?.profiles ?? [];

  function close() {
    if (switchProfile.isPending) return;
    setProblem(null);
    onClose();
  }

  function choose(name: string) {
    if (name === activeName || switchProfile.isPending) return;
    setProblem(null);
    switchProfile.mutate(name, {
      onSuccess: () => {
        setProblem(null);
        onClose();
      },
      onError: (error) => setProblem(describeError(error)),
    });
  }

  return (
    <Modal transparent visible={visible} animationType="slide" onRequestClose={close}>
      <View style={styles.backdrop}>
        <Pressable
          style={StyleSheet.absoluteFill}
          accessibilityRole="button"
          accessibilityLabel="关闭模型切换"
          disabled={switchProfile.isPending}
          onPress={close}
        />
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]} accessibilityViewIsModal>
          <View style={styles.handle} />
          <View style={styles.header}>
            <View>
              <Text style={styles.eyebrow}>MODEL</Text>
              <Text style={styles.title}>切换模型</Text>
            </View>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="关闭模型切换"
              hitSlop={10}
              disabled={switchProfile.isPending}
              onPress={close}
              style={styles.close}
            >
              <SymbolView name={{ ios: 'xmark', android: 'close', web: 'close' }} tintColor={theme.textMuted} size={18} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
            {profiles.isPending ? <ActivityIndicator color={theme.primary} style={{ marginVertical: 18 }} /> : null}
            {profiles.isError ? <Text style={styles.problem}>{describeError(profiles.error)}</Text> : null}
            {!profiles.isPending && !items.length ? (
              <Text style={styles.hint}>服务端还没有模型档案，去模型设置里新增一个。</Text>
            ) : null}

            {items.map((profile) => {
              const active = profile.name === activeName;
              const busy = switchProfile.isPending && switchProfile.variables === profile.name;
              return (
                <Pressable
                  key={profile.name}
                  accessibilityRole="radio"
                  accessibilityState={{ selected: active, disabled: switchProfile.isPending }}
                  disabled={switchProfile.isPending}
                  onPress={() => choose(profile.name)}
                  style={({ pressed }) => [styles.row, active && styles.rowActive, pressed && { opacity: 0.75 }]}
                >
                  <View style={[styles.orb, active && styles.orbActive]}>
                    <Text style={[styles.orbText, active && styles.orbTextActive]}>
                      {profile.name.slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                      <Text style={styles.name} numberOfLines={1}>{profile.name}</Text>
                      {profile.read_only ? <Text style={styles.base}>基础</Text> : null}
                    </View>
                    <Text style={styles.model} numberOfLines={1}>{profile.model}</Text>
                    <Text style={styles.url} numberOfLines={1}>{profile.base_url || '默认接口'}</Text>
                  </View>
                  {busy ? (
                    <ActivityIndicator size="small" color={theme.primary} />
                  ) : active ? (
                    <View style={styles.check}>
                      <SymbolView name={{ ios: 'checkmark', android: 'check', web: 'check' }} tintColor={theme.primary} size={13} />
                    </View>
                  ) : null}
                </Pressable>
              );
            })}

            {problem ? <Text style={styles.problem}>{problem}</Text> : null}
          </ScrollView>

          <View style={styles.footer}>
            <Button
              label="管理模型档案"
              variant="secondary"
              onPress={() => {
                onClose();
                router.push('/llm-settings');
              }}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: theme.overlay, justifyContent: 'flex-end' },
  sheet: {
    width: '100%',
    maxHeight: '82%',
    maxWidth: 640,
    alignSelf: 'center',
    backgroundColor: theme.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    borderWidth: 1,
    borderColor: theme.border,
  },
  handle: { width: 36, height: 4, borderRadius: 2, backgroundColor: theme.borderStrong, alignSelf: 'center', marginTop: 10 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingTop: 14, paddingBottom: 12 },
  eyebrow: { fontSize: 10, fontWeight: '700', letterSpacing: 1.4, color: theme.gold },
  title: { fontSize: 21, fontWeight: '600', color: theme.text, marginTop: 4 },
  close: { width: 36, height: 36, borderRadius: 12, borderWidth: 1, borderColor: theme.border, backgroundColor: theme.surfaceSoft, alignItems: 'center', justifyContent: 'center' },
  content: { paddingHorizontal: 20, paddingBottom: 8, gap: 8 },
  hint: { fontSize: 13, color: theme.textMuted, lineHeight: 20, paddingVertical: 8 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
    padding: 12,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: theme.border,
    backgroundColor: theme.surfaceSoft,
  },
  rowActive: { borderColor: theme.primary, backgroundColor: theme.primarySoft },
  orb: { width: 36, height: 36, borderRadius: 12, backgroundColor: theme.surfaceMuted, alignItems: 'center', justifyContent: 'center' },
  orbActive: { backgroundColor: theme.primary },
  orbText: { fontSize: 14, fontWeight: '700', color: theme.textMuted },
  orbTextActive: { color: theme.primaryInk },
  name: { fontSize: 15, fontWeight: '600', color: theme.text, flexShrink: 1 },
  base: { fontSize: 10, color: theme.gold, borderWidth: 1, borderColor: 'rgba(128,99,51,0.25)', borderRadius: 5, paddingHorizontal: 5, paddingVertical: 1 },
  model: { fontSize: 12, color: theme.textMuted, marginTop: 2 },
  url: { fontSize: 11, color: theme.textFaint, marginTop: 2 },
  check: { width: 24, height: 24, borderRadius: 12, backgroundColor: theme.surface, alignItems: 'center', justifyContent: 'center' },
  problem: { fontSize: 13, color: theme.danger, lineHeight: 20, paddingVertical: 6 },
  footer: { paddingHorizontal: 20, paddingTop: 8 },
});
