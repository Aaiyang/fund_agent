/**
 * 日期选择器（原生端）。Web 上走 `DateField.web.tsx` 里的浏览器原生控件 ——
 * `@react-native-community/datetimepicker` 在 web 渲染 null，不能共用。
 */

import DateTimePicker, { DateTimePickerAndroid } from '@react-native-community/datetimepicker';
import { useState } from 'react';
import { Modal, Platform, Pressable, Text, View } from 'react-native';

import { Button, FieldLabel } from '@/components/ui';
import { theme } from '@/constants/theme';
import { formatDay, parseDay } from '@/utils/format';

export function DateField({
  label,
  labelExtra,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  labelExtra?: React.ReactNode;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(() => parseDay(value));
  const [open, setOpen] = useState(false);

  function present() {
    if (Platform.OS === 'android') {
      DateTimePickerAndroid.open({
        value: parseDay(value),
        mode: 'date',
        display: 'calendar',
        onChange: (_event, picked) => picked && onChange(formatDay(picked)),
      });
      return;
    }
    setDraft(parseDay(value));
    setOpen(true);
  }

  return (
    <View style={{ marginBottom: 12 }}>
      <FieldLabel label={label} extra={labelExtra} />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${label}，${value || '未选择，点按选择日期'}`}
        onPress={present}
        style={({ pressed }) => [
          {
            borderWidth: 1,
            borderColor: theme.border,
            borderRadius: 10,
            paddingHorizontal: 12,
            paddingVertical: 10,
            backgroundColor: theme.surface,
            opacity: pressed ? 0.85 : 1,
          },
        ]}
      >
        <Text style={{ fontSize: 15, color: value ? theme.text : theme.textFaint }}>{value || placeholder}</Text>
      </Pressable>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <View style={{ flex: 1, justifyContent: 'center', padding: 24 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="关闭日期选择"
            onPress={() => setOpen(false)}
            style={{
              position: 'absolute',
              top: 0,
              right: 0,
              bottom: 0,
              left: 0,
              backgroundColor: 'rgba(17,24,39,0.45)',
            }}
          />
          <View style={{ backgroundColor: theme.surface, borderRadius: 16, padding: 18 }}>
            <DateTimePicker
              value={draft}
              mode="date"
              display="spinner"
              maximumDate={new Date()}
              onChange={(_event, picked) => picked && setDraft(picked)}
            />
            <View style={{ flexDirection: 'row', marginTop: 12 }}>
              <View style={{ flex: 1, marginRight: 6 }}>
                <Button label="取消" variant="secondary" onPress={() => setOpen(false)} />
              </View>
              <View style={{ flex: 1, marginLeft: 6 }}>
                <Button
                  label="确定"
                  onPress={() => {
                    onChange(formatDay(draft));
                    setOpen(false);
                  }}
                />
              </View>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}
