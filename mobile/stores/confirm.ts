/**
 * 全局独一份的确认弹窗，任何地方都能发起。
 *
 * 破坏性操作原先走 `window.confirm` / `Alert.alert`，碰上会吞掉原生对话框的
 * webview，就等于按钮按了没反应。现在改由应用自己渲染弹窗，确认这一步在
 * web、Android、iOS 上看起来和行为都一致。
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
