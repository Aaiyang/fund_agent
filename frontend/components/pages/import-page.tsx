'use client';

import { useState } from 'react';
import { ArrowLeft, FileImage, RefreshCw, Trash2, Upload } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type AccountItem,
  type ImportHistoryItem,
  type ManualPositionInput,
  createManualImport,
  getImportHistory,
  listAccounts,
  uploadScreenshots,
} from '@/lib/fund-api';
import { formatDateTime } from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '识别中',
  REVIEW_REQUIRED: '待确认',
  CONFIRMED: '已确认',
  APPLIED: '已导入',
  PARSE_FAILED: '识别失败',
  CANCELLED: '已取消',
};

type Row = {
  query: string;
  marketValue: string;
  profitLoss: string;
};

const EMPTY_ROW: Row = { query: '', marketValue: '', profitLoss: '' };
const MAX_IMAGES = 5;
const MAX_BYTES = 8 * 1024 * 1024;

export function ImportPage({
  token,
  initialAccountId = null,
  onBack,
  onOpenImport,
}: {
  token: string;
  initialAccountId?: number | null;
  onBack: () => void;
  onOpenImport: (importId: string) => void;
}) {
  const [mode, setMode] = useState<'manual' | 'screenshot'>('manual');
  const accounts = useResource<AccountItem[]>(() => listAccounts(token), token);
  const history = useResource<ImportHistoryItem[]>(
    () => getImportHistory(token),
    token,
  );
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const selectedAccount = accountId ?? accounts.data?.[0]?.id ?? null;

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5">
        <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
          IMPORT
        </p>
        <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
          导入持仓
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          导入是“当前持仓快照”的覆盖更新，不会据此推断买卖流水；任何结果都要经你确认后才会写入正式持仓。
        </p>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        {(['manual', 'screenshot'] as const).map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setMode(value)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              mode === value
                ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                : 'border-border bg-card/60 text-muted-foreground hover:text-foreground'
            }`}
          >
            {value === 'manual' ? '手动录入' : '上传持仓截图'}
          </button>
        ))}
      </div>

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <p className="text-sm font-semibold text-foreground">导入到账户</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {(accounts.data ?? []).map((account) => (
            <button
              key={account.id}
              type="button"
              onClick={() => setAccountId(account.id)}
              className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
                selectedAccount === account.id
                  ? 'border-primary/25 bg-primary/[0.08] font-medium text-primary'
                  : 'border-border bg-background/50 text-muted-foreground hover:text-foreground'
              }`}
            >
              {account.name}
            </button>
          ))}
          {(accounts.data?.length ?? 0) === 0 && (
            <p className="text-xs text-muted-foreground">
              还没有账户，请先在账户管理里创建一个。
            </p>
          )}
        </div>
      </section>

      {mode === 'manual' ? (
        <ManualImport
          token={token}
          accountId={selectedAccount}
          onOpenImport={onOpenImport}
        />
      ) : (
        <ScreenshotImport
          token={token}
          accountId={selectedAccount}
          onOpenImport={onOpenImport}
        />
      )}

      <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-foreground">导入记录</p>
          <Button
            variant="ghost"
            size="sm"
            className="rounded-lg"
            onClick={() => history.reload()}
          >
            <RefreshCw className={history.loading ? 'animate-spin' : ''} /> 刷新
          </Button>
        </div>
        {history.loading ? (
          <p className="mt-3 text-xs text-text-faint">正在读导入记录…</p>
        ) : (history.data?.length ?? 0) === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            还没有导入记录。从上方手动录入，或上传一张持仓截图。
          </p>
        ) : (
          <div className="mt-3 space-y-2">
            {history.data?.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onOpenImport(item.id)}
                className="flex w-full flex-wrap items-center gap-3 rounded-xl border border-border/70 bg-background/40 px-4 py-3 text-left hover:border-primary/25"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-foreground">
                    {item.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'} ·{' '}
                    {STATUS_LABEL[item.status] ?? item.status}
                  </p>
                  <p className="mt-0.5 text-[10px] text-text-faint">
                    账户 #{item.account_id} · 识别 {item.items_detected} 条 · 确认{' '}
                    {item.items_confirmed} 条 · {formatDateTime(item.created_at)}
                  </p>
                  {item.error_message && (
                    <p className="mt-1 text-[10px] text-destructive">
                      {item.error_message}
                    </p>
                  )}
                </div>
                <span className="text-[11px] text-primary">查看 ›</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ManualImport({
  token,
  accountId,
  onOpenImport,
}: {
  token: string;
  accountId: number | null;
  onOpenImport: (importId: string) => void;
}) {
  const [rows, setRows] = useState<Row[]>([{ ...EMPTY_ROW }]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  function update(index: number, patch: Partial<Row>) {
    setRows((current) =>
      current.map((row, position) =>
        position === index ? { ...row, ...patch } : row,
      ),
    );
  }

  async function submit() {
    setProblem('');
    if (accountId === null) {
      setProblem('请先创建持仓账户');
      return;
    }
    const filled = rows.filter((row) => row.query.trim());
    if (filled.length === 0) {
      setProblem('请至少填写一条持仓的基金代码或名称');
      return;
    }
    if (
      filled.some(
        (row) =>
          (row.marketValue.trim() !== '' &&
            Number.isNaN(Number(row.marketValue))) ||
          (row.profitLoss.trim() !== '' && Number.isNaN(Number(row.profitLoss))),
      )
    ) {
      setProblem('当前持有金额与持有收益需为数字');
      return;
    }
    const positions: ManualPositionInput[] = filled.map((row) => {
      const query = row.query.trim();
      const digits = /^\d{6}$/.test(query);
      return {
        fund_code: digits ? query : null,
        fund_name: digits ? null : query,
        market_value: row.marketValue.trim() === '' ? null : Number(row.marketValue),
        profit_loss: row.profitLoss.trim() === '' ? null : Number(row.profitLoss),
      };
    });
    setBusy(true);
    try {
      const batch = await createManualImport(token, accountId, positions);
      onOpenImport(batch.id);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '生成草稿失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
      <p className="text-sm font-semibold text-foreground">手动批量录入</p>
      <div className="mt-3 space-y-3">
        {rows.map((row, index) => (
          <div
            key={index}
            className="rounded-2xl border border-border/70 bg-background/40 p-4"
          >
            <div className="flex items-center justify-between">
              <p className="text-xs font-medium text-foreground">第 {index + 1} 条</p>
              {rows.length > 1 && (
                <Button
                  variant="ghost"
                  size="xs"
                  className="text-text-faint hover:text-destructive"
                  onClick={() =>
                    setRows((current) =>
                      current.filter((_, position) => position !== index),
                    )
                  }
                >
                  <Trash2 /> 移除
                </Button>
              )}
            </div>
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              <label className="block text-xs text-muted-foreground">
                基金（代码或名称）
                <Input
                  value={row.query}
                  onChange={(event) => update(index, { query: event.target.value })}
                  placeholder="011452 或基金名称"
                  className="mt-1.5 h-10 rounded-xl bg-card"
                />
              </label>
              <label className="block text-xs text-muted-foreground">
                当前持有金额
                <Input
                  inputMode="decimal"
                  value={row.marketValue}
                  onChange={(event) =>
                    update(index, { marketValue: event.target.value })
                  }
                  placeholder="请输入金额"
                  className="mt-1.5 h-10 rounded-xl bg-card"
                />
              </label>
              <label className="block text-xs text-muted-foreground">
                持有收益
                <Input
                  inputMode="decimal"
                  value={row.profitLoss}
                  onChange={(event) =>
                    update(index, { profitLoss: event.target.value })
                  }
                  placeholder="可留空"
                  className="mt-1.5 h-10 rounded-xl bg-card"
                />
              </label>
            </div>
          </div>
        ))}
      </div>
      {problem && (
        <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {problem}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          variant="outline"
          className="h-10 rounded-xl"
          onClick={() => setRows((current) => [...current, { ...EMPTY_ROW }])}
        >
          + 再加一条
        </Button>
        <Button
          className="h-10 rounded-xl"
          disabled={busy}
          onClick={() => void submit()}
        >
          {busy ? <RefreshCw className="animate-spin" /> : null} 生成待确认草稿
        </Button>
      </div>
      <p className="mt-2 text-[10px] text-text-faint">
        草稿不会改动正式持仓，下一步可逐条核对并确认。
      </p>
    </section>
  );
}

function ScreenshotImport({
  token,
  accountId,
  onOpenImport,
}: {
  token: string;
  accountId: number | null;
  onOpenImport: (importId: string) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  function choose(selected: FileList | null) {
    setProblem('');
    if (!selected) return;
    const incoming = Array.from(selected);
    const oversized = incoming.filter((file) => file.size > MAX_BYTES);
    if (oversized.length) {
      setProblem(`${oversized.length} 张图片超过 8MB，请先压缩后再上传`);
      return;
    }
    const merged = [...files, ...incoming];
    if (merged.length > MAX_IMAGES) {
      setProblem(`一次最多上传 ${MAX_IMAGES} 张截图`);
      return;
    }
    setFiles(merged);
  }

  async function submit() {
    setProblem('');
    if (accountId === null) {
      setProblem('请先选择持仓账户');
      return;
    }
    if (files.length === 0) {
      setProblem('请至少选择一张持仓截图');
      return;
    }
    setBusy(true);
    try {
      const accepted = await uploadScreenshots(token, accountId, files);
      onOpenImport(accepted.import_id);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '上传失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
      <p className="text-sm font-semibold text-foreground">
        截图识别（{files.length}/{MAX_IMAGES}）
      </p>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        支持多张，按基金代码去重合并；单张失败不影响其余结果。
      </p>
      <label className="mt-4 flex min-h-32 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-background/40 px-4 py-6 text-center hover:border-primary/30">
        <FileImage className="size-7 text-text-faint" />
        <span className="mt-2 text-xs text-muted-foreground">
          点击选择持仓截图，单张最多 8MB
        </span>
        <input
          type="file"
          accept="image/*"
          multiple
          className="sr-only"
          onChange={(event) => {
            choose(event.target.files);
            event.target.value = '';
          }}
        />
      </label>
      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {files.map((file) => (
            <span
              key={`${file.name}-${file.lastModified}`}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-[11px] text-text-soft"
            >
              {file.name}
              <button
                type="button"
                className="text-text-faint hover:text-destructive"
                onClick={() =>
                  setFiles((current) => current.filter((item) => item !== file))
                }
                aria-label={`移除 ${file.name}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {problem && (
        <p className="mt-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {problem}
        </p>
      )}
      <Button
        className="mt-4 h-10 rounded-xl"
        disabled={busy || files.length === 0}
        onClick={() => void submit()}
      >
        {busy ? <RefreshCw className="animate-spin" /> : <Upload />} 开始识别
      </Button>
    </section>
  );
}
