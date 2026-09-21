/**
 * Cross-screen UI selections (Zustand): which account view and which
 * watchlist group is active. Server data deliberately stays out of here.
 */

import { create } from 'zustand';

type UiState = {
  /** null means "全部账户" (aggregate across accounts). */
  accountId: number | null;
  /** null means "全部" (the spec's default group). */
  groupId: number | null;
  setAccountId: (accountId: number | null) => void;
  setGroupId: (groupId: number | null) => void;
};

export const useUiStore = create<UiState>((set) => ({
  accountId: null,
  groupId: null,
  setAccountId: (accountId) => set({ accountId }),
  setGroupId: (groupId) => set({ groupId }),
}));
