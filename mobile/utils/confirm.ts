/**
 * Cross-platform destructive-action confirmation.
 *
 * `Alert.alert` is a verified no-op in react-native-web (its export is an empty
 * function), so on web a confirm built on it silently swallows the action —
 * logout simply never happened. Native keeps the system dialog.
 */

import { Alert, Platform } from 'react-native';

export function confirmAction(title: string, message: string, onConfirm: () => void): void {
  if (Platform.OS === 'web') {
    if (window.confirm(`${title}\n${message}`)) onConfirm();
    return;
  }
  Alert.alert(title, message, [
    { text: '取消', style: 'cancel' },
    { text: '确定', style: 'destructive', onPress: onConfirm },
  ]);
}
