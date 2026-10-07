/**
 * 跨页面的 UI 选中状态（Zustand）：当前哪个账户视图、哪个自选分组生效。
 * 服务器数据刻意不往这里放。
 */

import { create } from 'zustand';

type UiState = {
  /** null 表示“全部账户”，即跨账户的汇总视图。 */
  accountId: number | null;
  /** null 表示“全部”，即 spec 里那个默认分组。 */
  groupId: number | null;
  setAccountId: (accountId: number | null) => void;
  setGroupId: (groupId: number | null) => void;
  /** 退回默认选中；切换登录用户时用。 */
  reset: () => void;
};

export const useUiStore = create<UiState>((set) => ({
  accountId: null,
  groupId: null,
  setAccountId: (accountId) => set({ accountId }),
  setGroupId: (groupId) => set({ groupId }),
  reset: () => set({ accountId: null, groupId: null }),
}));
