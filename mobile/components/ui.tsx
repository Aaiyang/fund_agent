/** Small layout and text primitives shared by every screen. */

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
  /** Bar rendered above the scroller so it stays visible while content moves. */
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
        <Pressable onPress={onAction}>
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

export function Row({ children }: { children: ReactNode }) {
  return <View style={{ flexDirection: 'row', flexWrap: 'wrap' }}>{children}</View>;
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

/** Bordered pill: the switcher and tag style used inside cards and forms. */
export function Chip({ label, active, onPress }: { label: string; active?: boolean; onPress?: () => void }) {
  return (
    <Pressable
      accessibilityRole={onPress ? 'button' : undefined}
      onPress={onPress}
      style={{
        paddingHorizontal: 12,
        paddingVertical: 6,
        borderRadius: 999,
        marginRight: 8,
        marginBottom: 8,
        backgroundColor: active ? theme.primary : theme.surface,
        borderWidth: 1,
        borderColor: active ? theme.primary : theme.border,
      }}
    >
      <Text style={{ fontSize: 13, color: active ? '#FFFFFF' : theme.text }}>{label}</Text>
    </Pressable>
  );
}

/**
 * Strip switcher item: bare text with an underline on the active one, the way a
 * mobile nav bar reads. Used by the pinned account and group rows above a table.
 * `accent` marks an item that navigates somewhere instead of selecting, so it
 * does not look like an unselected sibling.
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
      hitSlop={{ top: 6, bottom: 6 }}
      onPress={onPress}
      style={{
        marginRight: 18,
        paddingBottom: 5,
        borderBottomWidth: 2,
        borderBottomColor: active ? theme.primary : 'transparent',
      }}
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

export function Field({
  label,
  labelExtra,
  value,
  onChangeText,
  keyboardType = 'default',
  placeholder,
  secureTextEntry,
}: {
  label: string;
  labelExtra?: ReactNode;
  value: string;
  onChangeText: (text: string) => void;
  keyboardType?: 'default' | 'email-address' | 'numeric' | 'phone-pad';
  placeholder?: string;
  secureTextEntry?: boolean;
}) {
  return (
    <View style={{ marginBottom: 12 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 6 }}>
        <Text style={{ fontSize: 13, color: theme.textMuted }}>{label}</Text>
        {labelExtra}
      </View>
      <TextInput
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        placeholder={placeholder}
        placeholderTextColor={theme.textFaint}
        secureTextEntry={secureTextEntry}
        autoCapitalize={keyboardType === 'email-address' ? 'none' : 'sentences'}
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
