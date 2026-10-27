'use client';

import {
  CalendarClock,
  ChevronRight,
  FolderCog,
  Landmark,
  ListChecks,
  LogOut,
  Settings2,
  Sparkles,
  Star,
  Upload,
  UserRound,
  Wallet,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { UserProfile } from '@/lib/api';
import { type ImportHistoryItem, getImportHistory } from '@/lib/fund-api';
import { formatDate } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const STATUS_LABELS: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '识别中',
  REVIEW_REQUIRED: '待确认',
  CONFIRMED: '已确认',
  APPLIED: '已导入',
  PARSE_FAILED: '识别失败',
  CANCELLED: '已取消',
};

export function ProfilePage({
  token,
  user,
  onOpenPortfolio,
  onOpenWatchlist,
  onOpenGroups,
  onOpenManageAccounts,
  onOpenImport,
  onOpenImportReview,
  onOpenTransactions,
  onOpenAutoInvest,
  onOpenPersona,
  onOpenModel,
  onOpenAccount,
  onLogout,
}: {
  token: string;
  user: UserProfile;
  onOpenPortfolio: () => void;
  onOpenWatchlist: () => void;
  onOpenGroups: () => void;
  onOpenManageAccounts: () => void;
  onOpenImport: () => void;
  onOpenImportReview: (importId: string) => void;
  onOpenTransactions: () => void;
  onOpenAutoInvest: () => void;
  onOpenPersona: () => void;
  onOpenModel: () => void;
  onOpenAccount: () => void;
  onLogout: () => void;
}) {
  const history = useResource<ImportHistoryItem[]>(
    () => getImportHistory(token),
    token,
  );
  const displayName = user.username || user.email.split('@')[0];

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <div>
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          ACCOUNT
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          我的
        </h1>
      </div>

      <section className="mt-6 flex flex-wrap items-center gap-4 rounded-[24px] border border-border bg-card p-6 shadow-[0_18px_40px_rgba(33,58,42,0.05)]">
        <div className="grid size-16 place-items-center rounded-[20px] bg-gold/10 text-xl font-semibold text-gold">
          {displayName.slice(0, 1).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xl font-semibold text-foreground">{displayName}</p>
          <p className="mt-1 text-sm text-muted-foreground">{user.email}</p>
          {user.id && (
            <p className="mt-1 text-[11px] text-text-faint">用户 #{user.id}</p>
          )}
        </div>
        <Button variant="outline" className="rounded-xl" onClick={onOpenAccount}>
          <UserRound /> 修改资料
        </Button>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <section className="rounded-[24px] border border-border bg-card/70 p-5">
          <p className="text-sm font-semibold text-foreground">资产与自选</p>
          <div className="mt-3">
            <MenuRow
              icon={Wallet}
              label="持仓与账户"
              hint="总资产、账户汇总与持仓明细"
              onClick={onOpenPortfolio}
            />
            <MenuRow
              icon={FolderCog}
              label="账户管理"
              hint="新建、改名与删除持仓账户"
              onClick={onOpenManageAccounts}
            />
            <MenuRow
              icon={Upload}
              label="导入持仓"
              hint="手动录入或上传持仓截图"
              onClick={onOpenImport}
            />
            <MenuRow
              icon={ListChecks}
              label="交易与调整记录"
              hint="逐笔查看买入、卖出、定投与修正"
              onClick={onOpenTransactions}
            />
            <MenuRow
              icon={CalendarClock}
              label="定投计划"
              hint="扣款排期与已结算期数"
              onClick={onOpenAutoInvest}
            />
          </div>
        </section>

        <section className="rounded-[24px] border border-border bg-card/70 p-5">
          <p className="text-sm font-semibold text-foreground">自选与 AI</p>
          <div className="mt-3">
            <MenuRow
              icon={Star}
              label="自选基金"
              hint="搜索、分组与移除"
              onClick={onOpenWatchlist}
            />
            <MenuRow
              icon={FolderCog}
              label="自选分组"
              hint="新建、改名与组内排序"
              onClick={onOpenGroups}
            />
            <MenuRow
              icon={Sparkles}
              label="用户画像"
              hint="风险偏好、目标与回答习惯"
              onClick={onOpenPersona}
            />
            <MenuRow
              icon={Settings2}
              label="模型中心"
              hint="当前模型、档案与 API Key"
              onClick={onOpenModel}
            />
          </div>
        </section>
      </div>

      <section className="mt-4 rounded-[24px] border border-border bg-card/70 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">最近导入</p>
          <span className="text-[10px] text-text-faint">
            {history.data?.length ?? 0} 个批次
          </span>
        </div>
        {history.loading ? (
          <p className="mt-3 text-xs text-text-faint">正在读导入记录…</p>
        ) : history.error ? (
          <p className="mt-3 text-xs text-destructive">{history.error}</p>
        ) : (history.data?.length ?? 0) === 0 ? (
          <div className="mt-4 rounded-xl border border-dashed border-border px-4 py-6 text-center">
            <p className="text-xs text-muted-foreground">
              还没有导入记录。手动录入或截图识别后，会在这里留下批次。
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3 rounded-lg"
              onClick={onOpenImport}
            >
              <Upload /> 去导入
            </Button>
          </div>
        ) : (
          <div className="mt-3 space-y-2">
            {history.data?.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onOpenImportReview(item.id)}
                className="flex w-full items-center gap-3 rounded-xl border border-border/70 bg-background/40 px-3 py-2.5 text-left hover:border-primary/25"
              >
                <Landmark className="size-4 text-text-faint" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-foreground">
                    {item.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'} ·
                    账户 #{item.account_id}
                  </p>
                  <p className="mt-0.5 text-[10px] text-text-faint">
                    {formatDate(item.created_at)} · 识别 {item.items_detected} 条
                    {item.error_message ? ` · ${item.error_message}` : ''}
                  </p>
                </div>
                <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-text-soft">
                  {STATUS_LABELS[item.status] ?? item.status}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="mt-4 flex items-center justify-between rounded-[24px] border border-border bg-card/70 p-5">
        <div>
          <p className="text-sm font-semibold text-foreground">退出登录</p>
          <p className="mt-1 text-xs text-muted-foreground">
            账户数据会保留，下次再回来。
          </p>
        </div>
        <Button variant="destructive" className="rounded-xl" onClick={onLogout}>
          <LogOut /> 退出
        </Button>
      </section>
    </div>
  );
}

function MenuRow({
  icon: Icon,
  label,
  hint,
  onClick,
}: {
  icon: typeof Wallet;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 border-b border-border/70 py-3 text-left last:border-0 hover:text-primary"
    >
      <span className="grid size-8 place-items-center rounded-xl bg-primary/[0.06] text-primary">
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-foreground">{label}</span>
        <span className="mt-0.5 block text-[11px] text-text-faint">{hint}</span>
      </span>
      <ChevronRight className="size-4 text-text-faint" />
    </button>
  );
}
