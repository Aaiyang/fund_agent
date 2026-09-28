/**
 * 买入确认日期 + 15:00 前后，共用的录入控件。
 *
 * 场外基金按未知价成交，这个日期决定成本、收益和持有天数，所以手动表单与导入
 * 草稿共用同一套控件和默认值。规则本身只在感叹号里讲一次——两个选项上再各挂
 * 一句解释，就把一行能放下的东西变成了两行噪音。
 */

import { useState } from 'react';
import { Modal, Pressable, Text, View } from 'react-native';
import { SymbolView } from 'expo-symbols';

import { Button, Chip, Field } from '@/components/ui';
import { theme } from '@/constants/theme';
import { formatDateTime, isCalendarDate, localToday } from '@/utils/format';

const RULES = [
  '15:00 前提交，按当天公布的净值确认份额。',
  '15:00 后提交，顺延到下一个交易日的净值。',
  '周末和节假日不确认交易，继续顺延到下一个交易日。',
  '持仓成本、持有收益和持有天数都从确认那天算起。',
];

export function PurchaseDateFields({
  value,
  onChangeText,
  afterCutoff,
  onAfterCutoff,
}: {
  value: string;
  onChangeText: (value: string) => void;
  afterCutoff: boolean;
  onAfterCutoff: (value: boolean) => void;
}) {
  const [explaining, setExplaining] = useState(false);

  return (
    <>
      <Field
        label="买入确认日期"
        labelExtra={
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="买入时间怎么算"
            hitSlop={8}
            onPress={() => setExplaining(true)}
            style={{ marginLeft: 6 }}
          >
            <SymbolView
              name={{ ios: 'exclamationmark.circle', android: 'error', web: 'error' }}
              tintColor={theme.textFaint}
              size={15}
            />
          </Pressable>
        }
        value={value}
        onChangeText={onChangeText}
        placeholder="请输入买入确认日期（YYYY-MM-DD）"
      />
      <View style={{ flexDirection: 'row', marginBottom: 12 }}>
        <Chip label="15:00前" active={!afterCutoff} onPress={() => onAfterCutoff(false)} />
        <Chip label="15:00后" active={afterCutoff} onPress={() => onAfterCutoff(true)} />
      </View>

      <Modal visible={explaining} transparent animationType="fade" onRequestClose={() => setExplaining(false)}>
        <View style={{ flex: 1, justifyContent: 'center', padding: 24 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="关闭说明"
            onPress={() => setExplaining(false)}
            style={{ position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(17,24,39,0.45)' }}
          />
          <View style={{ backgroundColor: theme.surface, borderRadius: 16, padding: 18 }}>
            <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text, marginBottom: 10 }}>买入时间怎么算</Text>
            {RULES.map((rule) => (
              <Text key={rule} style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20 }}>
                · {rule}
              </Text>
            ))}
            <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20, marginTop: 8 }}>
              不知道具体哪天就留空，系统不会替你猜一个买入日。
            </Text>
            <View style={{ marginTop: 14 }}>
              <Button label="知道了" variant="secondary" onPress={() => setExplaining(false)} />
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}

/** The stored date, else the day the snapshot was taken, else today on the device. */
export function initialPurchaseDate(stored: string | null | undefined, snapshotAt?: string | null): string {
  if (stored) return stored;
  return snapshotAt ? formatDateTime(snapshotAt).slice(0, 10) : localToday();
}

/** Reason the date cannot be saved, or null when it is usable or left blank. */
export function purchaseDateProblem(value: string): string | null {
  return value.trim() !== '' && !isCalendarDate(value) ? '买入确认日期格式应为 YYYY-MM-DD' : null;
}
