/**
 * Group picker shown before a fund is added to the watchlist.
 *
 * Adding must be an explicit choice (spec 3.3 分组): the caller opens this
 * sheet and only fires the add on confirm, so there is no silent path that
 * drops the fund into whatever group happens to be filtered.
 */

import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, TextInput, View } from 'react-native';

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
  /** groupIds is empty for the explicit "不分组" choice. */
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
    if (!name) return;
    setCreating(true);
    const id = await onCreateGroup(name);
    setCreating(false);
    if (id !== null) {
      setNewName('');
      setSelected((current) => [...current, id]);
    }
  }

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={{ flex: 1, backgroundColor: 'rgba(17,24,39,0.45)', justifyContent: 'flex-end' }}>
        <View style={{ backgroundColor: theme.background, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: 16 }}>
          <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text }} numberOfLines={1}>
            加入自选：{fundName}
          </Text>
          <Text style={{ fontSize: 13, color: theme.textMuted, marginTop: 4 }}>请选择分组，或明确选择不分组。</Text>

          <ScrollView style={{ maxHeight: 260, marginTop: 12 }}>
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
                onPress={createGroup}
                style={{ paddingHorizontal: 14, paddingVertical: 11, borderRadius: 10, backgroundColor: creating ? theme.border : theme.surface, borderWidth: 1, borderColor: theme.border }}
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
    </Modal>
  );
}
