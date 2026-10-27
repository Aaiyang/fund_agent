/**
 * 跨页面的 UI 选中状态（Zustand）：当前哪个账户视图、哪个自选分组生效。
 * 服务器数据刻意不往这里放。
 */

import { create } from 'zustand';

type UiState = {
  /** null 表示“全部账户”，即跨账户的汇总视图。 */
  accountId: number | null;
  /** null 表示”全部”，即 spec 里那个默认分组。 */
  groupId: number | null;
  /**
   * 当前在聊的会话。
   *
   * 放这里而不是本地 state：跳到会话列表页选完再回来，Agent tab 已经卸载过，
   * 组件内的状态留不住这条选择。
   */
  agentSessionId: string | null;
  /** 会话面板是否滑出。放这里是因为开关分属两个组件：表头按钮与聊天页。 */
  agentSessionsOpen: boolean;
  /** 当前这条回答是否还在生成；表头用它显示状态，不必把整个聊天状态提上去。 */
  agentStreaming: boolean;
  setAccountId: (accountId: number | null) => void;
  setGroupId: (groupId: number | null) => void;
  setAgentSessionId: (sessionId: string | null) => void;
  setAgentSessionsOpen: (open: boolean) => void;
  setAgentStreaming: (streaming: boolean) => void;
  /** 退回默认选中；切换登录用户时用。 */
  reset: () => void;
};

export const useUiStore = create<UiState>((set) => ({
  accountId: null,
  groupId: null,
  agentSessionId: null,
  agentSessionsOpen: false,
  agentStreaming: false,
  setAccountId: (accountId) => set({ accountId }),
  setGroupId: (groupId) => set({ groupId }),
  setAgentSessionId: (sessionId) => set({ agentSessionId: sessionId }),
  setAgentSessionsOpen: (open) => set({ agentSessionsOpen: open }),
  setAgentStreaming: (streaming) => set({ agentStreaming: streaming }),
  reset: () => set({ accountId: null, groupId: null, agentSessionId: null, agentSessionsOpen: false, agentStreaming: false }),
}));
