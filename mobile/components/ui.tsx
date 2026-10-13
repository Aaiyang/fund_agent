/** 所有页面共用的布局与文字小构件。 */

import { type ReactNode } from 'react';
import { type StyleProp, type ViewStyle, Pressable, RefreshControl, ScrollView, Text, TextInput, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { theme } from '@/constants/theme';

export function Screen({
  children,
  scroll = true,
  refreshing,
  onRefresh,
  pinned,
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  /** 渲染在滚动容器上方的横条，内容滚动时它保持可见。 */
  pinned?: ReactNode;
}) {
  return (
    <SafeAreaView edges={['bottom']} style={{ flex: 1, backgroundColor: theme.background }}>
      {pinned ? (
        <View
          style={{
            backgroundColor: theme.surface,
            borderBottomWidth: 1,
            borderColor: theme.border,
            paddingHorizontal: theme.gap,
            paddingVertical: 8,
          }}
        >
          {pinned}
        </View>
      ) : null}
      {scroll ? (
        <ScrollView
          contentContainerStyle={{ padding: theme.gap, paddingBottom: 32 }}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            onRefresh ? (
              <RefreshControl refreshing={Boolean(refreshing)} onRefresh={onRefresh} tintColor={theme.primary} colors={[theme.primary]} />
            ) : undefined
          }
        >
          {children}
        </ScrollView>
      ) : (
        <View style={{ flex: 1 }}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return (
    <View style={[{ backgroundColor: theme.surface, borderRadius: theme.radius, padding: theme.gap, marginBottom: theme.gap }, style]}>
      {children}
    </View>
  );
}

export function SectionTitle({ title, action, onAction }: { title: string; action?: string; onAction?: () => void }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
      <Text style={{ fontSize: 15, fontWeight: '600', color: theme.text }}>{title}</Text>
      {action ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={action}
          hitSlop={10}
          onPress={onAction}
          style={({ pressed }) => [{ paddingHorizontal: 4, paddingVertical: 2 }, pressed && { opacity: 0.7 }]}
        >
          <Text style={{ fontSize: 13, color: theme.primary }}>{action}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function Stat({
  label,
  value,
  tone = 'normal',
}: {
  label: string;
  value: string;
  tone?: 'normal' | 'up' | 'down' | 'muted';
}) {
  const color = tone === 'up' ? theme.up : tone === 'down' ? theme.down : tone === 'muted' ? theme.textMuted : theme.text;
  return (
    <View style={{ flex: 1, minWidth: 96, marginBottom: 10 }}>
      <Text style={{ fontSize: 12, color: theme.textFaint, marginBottom: 4 }}>{label}</Text>
      <Text style={{ fontSize: 16, fontWeight: '600', color }} numberOfLines={1}>
        {value}
      </Text>
    </View>
  );
}

export function Row({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[{ flexDirection: 'row', flexWrap: 'wrap' }, style]}>{children}</View>;
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  loading,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'danger';
  disabled?: boolean;
  loading?: boolean;
}) {
  const background = variant === 'primary' ? theme.primary : variant === 'danger' ? theme.danger : theme.surface;
  const color = variant === 'secondary' ? theme.text : '#FFFFFF';
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        {
          backgroundColor: background,
          borderRadius: 10,
          paddingVertical: 12,
          alignItems: 'center',
          borderWidth: variant === 'secondary' ? 1 : 0,
          borderColor: theme.border,
          opacity: disabled || loading ? 0.55 : pressed ? 0.9 : 1,
        },
      ]}
    >
      <Text style={{ color, fontSize: 15, fontWeight: '600' }}>{loading ? '处理中…' : label}</Text>
    </Pressable>
  );
}

/**
 * 带边框的胶囊：卡片与表单里切换、标签的样式。
 *
 * 不传 `onPress` 时它是只读标签（比如"未接入"），所以按压态只在可点时才给。
 */
export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress?: () => void }) {
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={onPress ? label : undefined}
      onPress={onPress}
      style={({ pressed }) => ({
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 999,
        marginRight: 8,
        marginBottom: 8,
        backgroundColor: active ? theme.primary : theme.surface,
        borderWidth: 1,
        borderColor: active ? theme.primary : theme.border,
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Text style={{ fontSize: 13, color: active ? '#FFFFFF' : theme.text }}>{label}</Text>
    </Pressable>
  );
}

/**
 * 条状切换项：裸文字，选中的一项底下加一条横线，按移动端导航栏的样子来。
 * 用在表格上方固定的账户行与分组行。`accent` 标记那些负责跳转而不是
 * 选中的条目，免得它看起来像个没选中的同组项。
 */
export function NavTab({
  label,
  active,
  accent,
  onPress,
}: {
  label: string;
  active?: boolean;
  accent?: boolean;
  onPress?: () => void;
}) {
  return (
    <Pressable
      accessibilityRole={onPress ? 'tab' : undefined}
      accessibilityState={{ selected: Boolean(active) }}
      hitSlop={{ top: 10, bottom: 10 }}
      onPress={onPress}
      style={({ pressed }) => ({
        marginRight: 18,
        paddingBottom: 5,
        borderBottomWidth: 2,
        borderBottomColor: active ? theme.primary : 'transparent',
        opacity: pressed ? 0.7 : 1,
      })}
    >
      <Text
        style={{
          fontSize: 14,
          fontWeight: active ? '600' : '400',
          color: active || accent ? theme.primary : theme.textMuted,
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export function Badge({ label, tone = 'warning' }: { label: string; tone?: 'warning' | 'danger' | 'muted' }) {
  const palette = {
    warning: { background: theme.warningBackground, color: theme.warning },
    danger: { background: '#FEE2E2', color: theme.danger },
    muted: { background: '#F3F4F6', color: theme.textMuted },
  }[tone];
  return (
    <View style={{ backgroundColor: palette.background, borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 }}>
      <Text style={{ fontSize: 11, color: palette.color }}>{label}</Text>
    </View>
  );
}

/** 输入框上方的标签行，文本框与日期选择器共用。 */
export function FieldLabel({ label, extra }: { label: string; extra?: ReactNode }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
      <Text style={{ fontSize: 13, color: theme.textMuted }}>{label}</Text>
      {extra}
    </View>
  );
}

export function Field({
  label,
  labelExtra,
  value,
  onChangeText,
  keyboardType = 'default',
  placeholder,
  secureTextEntry,
  autoCapitalize,
}: {
  label: string;
  labelExtra?: ReactNode;
  value: string;
  onChangeText: (text: string) => void;
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'phone-pad';
  placeholder?: string;
  secureTextEntry?: boolean;
  /** 接口地址与 API Key 这类串不能被首字母大写改写，调用点显式关掉。 */
  autoCapitalize?: 'none' | 'sentences' | 'words' | 'characters';
}) {
  return (
    <View style={{ marginBottom: 12 }}>
      <FieldLabel label={label} extra={labelExtra} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        placeholder={placeholder}
        placeholderTextColor={theme.textFaint}
        secureTextEntry={secureTextEntry}
        autoCapitalize={autoCapitalize ?? (keyboardType === 'email-address' ? 'none' : 'sentences')}
        style={{
          borderWidth: 1,
          borderColor: theme.border,
          borderRadius: 10,
          paddingHorizontal: 12,
          paddingVertical: 10,
          fontSize: 15,
          color: theme.text,
          backgroundColor: theme.surface,
        }}
      />
    </View>
  );
}
