/** The dialog behind `confirmAction`, rendered by the app rather than the OS. */

import { Modal, Pressable, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { theme } from '@/constants/theme';
import { useConfirmStore } from '@/stores/confirm';

export function ConfirmDialog() {
  const ask = useConfirmStore((state) => state.ask);
  const hide = useConfirmStore((state) => state.hide);

  return (
    <Modal visible={ask !== null} transparent animationType="fade" onRequestClose={hide}>
      <View style={{ flex: 1, justifyContent: 'center', padding: 24 }}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="取消"
          onPress={hide}
          style={{
            position: 'absolute',
            top: 0,
            right: 0,
            bottom: 0,
            left: 0,
            backgroundColor: 'rgba(17,24,39,0.45)',
          }}
        />
        {ask ? (
          <View style={{ backgroundColor: theme.surface, borderRadius: 16, padding: 18 }}>
            <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text }}>{ask.title}</Text>
            <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20, marginTop: 8 }}>{ask.message}</Text>
            <View style={{ flexDirection: 'row', marginTop: 16 }}>
              <View style={{ flex: 1, marginRight: 6 }}>
                <Button label="取消" variant="secondary" onPress={hide} />
              </View>
              <View style={{ flex: 1, marginLeft: 6 }}>
                <Button
                  label={ask.confirmLabel}
                  variant="danger"
                  onPress={() => {
                    hide();
                    ask.onConfirm();
                  }}
                />
              </View>
            </View>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}
