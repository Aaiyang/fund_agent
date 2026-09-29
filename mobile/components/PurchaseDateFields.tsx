/**
 * 买入日期，以及只有下单才需要的 15:00 前后。
 *
 * 场外基金按未知价成交，确认日决定这一单按哪一场净值算，所以加减仓用带 cutoff
 * 的那一组；同步持仓只是照抄三方页面，它的日期是「第一次买入哪天」，没有 cutoff
 * 可言，用只填日期那一组。规则说明挂在感叹号上，两个选项各带一句解释会把一行
 * 能放下的东西变成两行噪音。
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
  '这一单换成多少份额、成本按哪天算，都由确认日的净值决定。',
];

/**
 * The closing line differs by screen. An order cannot exist without a day —
 * that day is what prices it — while a holdings snapshot may legitimately not
 * know when the fund was first bought.
 */
const ORDER_NOTE = '这一单按哪一天的净值成交，必须填；不确定的话去三方 App 的交易记录里查。';
const SNAPSHOT_NOTE = '不知道具体哪天就留空，系统不会替你猜一个买入日。';

/** 买入确认日期 + 感叹号说明，加减仓与导入草稿都用它。 */
export function PurchaseDateField({
  value,
  onChangeText,
  label = '买入确认日期',
  required = false,
}: {
  value: string;
  onChangeText: (value: string) => void;
  label?: string;
  required?: boolean;
}) {
  const [explaining, setExplaining] = useState(false);

  return (
    <>
      <Field
        label={label}
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

      <Modal visible={explaining} transparent animationType="fade" onRequestClose={() => setExplaining(false)}>
        <View style={{ flex: 1, justifyContent: 'center', padding: 24 }}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="关闭说明"
            onPress={() => setExplaining(false)}
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
            <Text style={{ fontSize: 16, fontWeight: '700', color: theme.text, marginBottom: 10 }}>买入时间怎么算</Text>
            {RULES.map((rule) => (
              <Text key={rule} style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20 }}>
                · {rule}
              </Text>
            ))}
            <Text style={{ fontSize: 13, color: theme.textMuted, lineHeight: 20, marginTop: 8 }}>
              {required ? ORDER_NOTE : SNAPSHOT_NOTE}
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

/** The same date plus which side of the cutoff the order fell on. */
export function PurchaseDateFields({
  value,
  onChangeText,
  afterCutoff,
  onAfterCutoff,
  required = false,
}: {
  value: string;
  onChangeText: (value: string) => void;
  afterCutoff: boolean;
  onAfterCutoff: (value: boolean) => void;
  required?: boolean;
}) {
  return (
    <>
      <PurchaseDateField value={value} onChangeText={onChangeText} required={required} />
      <View style={{ flexDirection: 'row', marginBottom: 12 }}>
        <Chip label="15:00前" active={!afterCutoff} onPress={() => onAfterCutoff(false)} />
        <Chip label="15:00后" active={afterCutoff} onPress={() => onAfterCutoff(true)} />
      </View>
    </>
  );
}

/** The stored date, else the day the snapshot was taken, else today on the device. */
export function initialPurchaseDate(stored: string | null | undefined, snapshotAt?: string | null): string {
  if (stored) return stored;
  return snapshotAt ? formatDateTime(snapshotAt).slice(0, 10) : localToday();
}

/** Reason the date cannot be saved: on an order it is mandatory, on a snapshot blank is fine. */
export function purchaseDateProblem(value: string, required = false): string | null {
  const trimmed = value.trim();
  if (trimmed === '') return required ? '请填写买入确认日期' : null;
  return isCalendarDate(trimmed) ? null : '买入确认日期格式应为 YYYY-MM-DD';
}
