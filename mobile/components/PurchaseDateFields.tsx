/**
 * 买入确认日期 + 15:00 前后，共用的录入控件。
 *
 * 场外基金按未知价成交：15:00 前提交用当日净值，之后顺延到下一场。这个日期
 * 决定成本、收益和持有天数，所以手动表单与导入草稿用的是同一个控件、同一套默认值。
 */

import { View } from 'react-native';

import { Chip, Field } from '@/components/ui';
import { formatDateTime, isCalendarDate, localToday } from '@/utils/format';

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
  return (
    <>
      <Field
        label="买入确认日期"
        value={value}
        onChangeText={onChangeText}
        placeholder="请输入买入确认日期（YYYY-MM-DD）"
      />
      <View style={{ flexDirection: 'row', marginBottom: 12 }}>
        <Chip label="15:00前，按当日净值" active={!afterCutoff} onPress={() => onAfterCutoff(false)} />
        <Chip label="15:00后，按次日净值" active={afterCutoff} onPress={() => onAfterCutoff(true)} />
      </View>
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
