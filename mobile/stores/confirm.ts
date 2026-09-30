/**
 * The app's one confirmation dialog, asked for from anywhere.
 *
 * Destructive actions used to go through `window.confirm` / `Alert.alert`, and a
 * webview that swallows native dialogs turned that into a button that silently
 * did nothing. The dialog is rendered by the app instead, so the confirm step
 * looks and behaves the same on web, Android and iOS.
 */

import { create } from 'zustand';

export type Ask = {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
};

type ConfirmState = {
  ask: Ask | null;
  show: (ask: Ask) => void;
  hide: () => void;
};

export const useConfirmStore = create<ConfirmState>((set) => ({
  ask: null,
  show: (ask) => set({ ask }),
  hide: () => set({ ask: null }),
}));
