/**
 * 日期选择器（Web 端）。
 *
 * 直接用浏览器原生的 `<input type="date">`：日历弹层、键盘输入、无障碍都是
 * 现成的，而 `@react-native-community/datetimepicker` 在 web 上渲染 null，
 * 两边没法共用同一个实现。
 */

import { Text, View } from 'react-native';

import { FieldLabel } from '@/components/ui';
import { theme } from '@/constants/theme';

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
  return (
    <View style={{ marginBottom: 12 }}>
      <FieldLabel label={label} extra={labelExtra} />
      <input
        type="date"
        value={value}
        max={new Date().toISOString().slice(0, 10)}
        aria-label={placeholder ? `${label}，${placeholder}` : label}
        onChange={(event) => onChange(event.target.value)}
        style={{
          borderWidth: 1,
          borderColor: theme.border,
          borderRadius: 10,
          paddingLeft: 12,
          paddingRight: 12,
          paddingTop: 9,
          paddingBottom: 9,
          fontSize: 15,
          color: theme.text,
          backgroundColor: theme.surface,
          width: '100%',
          fontFamily: 'inherit',
          outline: 'none',
          boxSizing: 'border-box',
        }}
      />
      {!value && placeholder ? (
        <Text style={{ fontSize: 12, color: theme.textFaint, marginTop: 4 }}>{placeholder}</Text>
      ) : null}
    </View>
  );
}
