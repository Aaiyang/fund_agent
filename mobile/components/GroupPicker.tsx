/**
 * 加自选前弹出的分组选择面板。
 *
 * 加入必须是显式选择（spec 3.3 分组）：调用方打开这个面板，只在用户点确认
 * 后才发起添加，不存在把基金悄悄塞进当前筛选到的某个分组的路径。
 */

import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from 'react-native';

import { Button, Chip } from '@/components/ui';
import { theme } from '@/constants/theme';
import type { WatchlistGroup } from '@/hooks/useWatchlist';

export function GroupPicker({
  visible,
  fundName,
  groups,
  busy,
  onCancel,
  onConfirm,
  onCreateGroup,
}: {
  visible: boolean;
  fundName: string;
  groups: WatchlistGroup[];
  busy?: boolean;
  onCancel: () => void;
  /** 用户明确选“不分组”时，groupIds 为空。 */
  onConfirm: (groupIds: number[]) => void;
  onCreateGroup: (name: string) => Promise<number | null>;
}) {
  const [selected, setSelected] = useState<number[]>([]);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);

  function reset() {
    setSelected([]);
    setNewName('');
    setCreating(false);
  }

  function close() {
    reset();
    onCancel();
  }

  async function createGroup() {
    const name = newName.trim();
    if (!name || creating) return;
    setCreating(true);
    const id = await onCreateGroup(name);
    setCreating(false);
    if (id !== null) {
      setNewName('');
      setSelected((current) => [...current, id]);
    }
  }

  // 面板贴底部弹出，输入框就在按钮上方：不避让的话键盘会把“确认加入”整个盖住。
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <KeyboardAvoidingView
        style={{ flex: 1, justifyContent: 'flex-end' }}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      >
        <View style={{ flex: 1, backgroundColor: 'rgba(17,24,39,0.45)', justifyContent: 'flex-end' }}>
          <View
            style={{
              backgroundColor: theme.background,
              borderTopLeftRadius: 16,
              borderTopRightRadius: 16,
              padding: 16,
            }}
          >
            <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text }} numberOfLines={1}>
              加入自选：{fundName}
            </Text>
            <Text style={{ fontSize: 13, color: theme.textMuted, marginTop: 4 }}>请选择分组，或明确选择不分组。</Text>

            <ScrollView style={{ maxHeight: 260, marginTop: 12 }} keyboardShouldPersistTaps="handled">
              <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>
                {groups.length === 0 ? (
                  <Text style={{ fontSize: 13, color: theme.textFaint, marginBottom: 8 }}>还没有分组，可先新建一个或选择不分组</Text>
                ) : null}
                {groups.map((group) => (
                  <Chip
                    key={group.id}
                    label={`${group.name}(${group.fund_count})`}
                    active={selected.includes(group.id)}
                    onPress={() =>
                      setSelected((current) =>
                        current.includes(group.id) ? current.filter((id) => id !== group.id) : [...current, group.id],
                      )
                    }
                  />
                ))}
              </View>

              <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 4 }}>
                <TextInput
                  value={newName}
                  onChangeText={setNewName}
                  placeholder="请输入新分组名称"
                  placeholderTextColor={theme.textFaint}
                  returnKeyType="done"
                  onSubmitEditing={createGroup}
                  style={{
                    flex: 1,
                    borderWidth: 1,
                    borderColor: theme.border,
                    borderRadius: 10,
                    paddingHorizontal: 12,
                    paddingVertical: 10,
                    fontSize: 14,
                    color: theme.text,
                    backgroundColor: theme.surface,
                    marginRight: 8,
                  }}
                />
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="新建分组并选中"
                  hitSlop={10}
                  disabled={creating || !newName.trim()}
                  onPress={createGroup}
                  style={({ pressed }) => [
                    {
                      paddingHorizontal: 14,
                      paddingVertical: 11,
                      borderRadius: 10,
                      backgroundColor: creating ? theme.border : theme.surface,
                      borderWidth: 1,
                      borderColor: theme.border,
                      opacity: !newName.trim() || creating ? 0.55 : pressed ? 0.85 : 1,
                    },
                  ]}
                >
                  <Text style={{ color: theme.primary, fontSize: 14 }}>{creating ? '…' : '新建'}</Text>
                </Pressable>
              </View>
            </ScrollView>

            <View style={{ marginTop: 14 }}>
              <Button
                label={selected.length > 0 ? `确认加入（${selected.length} 个分组）` : '确认加入（不分组）'}
                loading={busy}
                onPress={() => {
                  onConfirm(selected);
                  reset();
                }}
              />
            </View>
            <View style={{ marginTop: 8 }}>
              <Button label="取消" variant="secondary" onPress={close} />
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}
