'use client';

import { useEffect, useState } from 'react';
import { ArrowLeft, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  type ImportBatch,
  type ImportItem,
  confirmImport,
  deleteImport,
  getImportDetail,
  updateImportItem,
} from '@/lib/fund-api';
import {
  formatMoney,
  formatReturn,
  formatSignedMoney,
} from '@/lib/fund-format';
import { useResource } from '@/lib/use-resource';

const ISSUE_LABEL: Record<string, string> = {
  fund_unresolved: '未匹配到基金',
  missing_market_value_and_shares: '缺少金额与份额',
  low_confidence: '匹配置信度低',
  market_value_suspiciously_large: '金额异常偏大',
  profit_loss_inconsistent_with_value: '收益与金额不匹配',
  profit_loss_rate_out_of_range: '收益率超出范围',
  duplicate_fund_different_values: '同一基金金额冲突',
  fund_name_truncated: '名称被截断',
  profit_and_rate_disagree: '收益与收益率一正一负',
};

const STATUS_LABEL: Record<string, string> = {
  UPLOADED: '已上传',
  PARSING: '识别中',
  REVIEW_REQUIRED: '待确认',
  CONFIRMED: '已确认',
  APPLIED: '已导入',
  PARSE_FAILED: '识别失败',
  CANCELLED: '已取消',
};

export function ImportReviewPage({
  token,
  importId,
  onBack,
  onOpenPortfolio,
  onDeleted,
}: {
  token: string;
  importId: string;
  onBack: () => void;
  onOpenPortfolio: () => void;
  onDeleted: () => void;
}) {
  const detail = useResource<ImportBatch>(
    () => getImportDetail(token, importId),
    `${token}:${importId}`,
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState('');
  const [problem, setProblem] = useState('');
  const status = detail.data?.status;
  const pending = status === 'UPLOADED' || status === 'PARSING';
  const reload = detail.reload;

  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => reload(), 2500);
    return () => window.clearInterval(timer);
  }, [pending, reload]);

  const batch = detail.data;
  const eligible =
    batch?.items?.filter(
      (item) =>
        Boolean(item.matched_fund_code) &&
        (item.user_action ??
          (item.validation_status === 'error' ? 'SKIP' : 'UPDATE')) === 'UPDATE',
    ).length ?? 0;

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setProblem('');
    try {
      const confirmed = await confirmImport(token, importId);
      setResult(
        `已写入 ${confirmed.applied} 条持仓，跳过 ${confirmed.skipped} 条。原图已删除。`,
      );
      detail.reload();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '确认导入失败');
    } finally {
      setBusy(false);
    }
  }

  async function removeBatch() {
    if (!window.confirm('取消并删除这个导入批次？草稿不会写入持仓。')) return;
    setBusy(true);
    try {
      await deleteImport(token, importId);
      onDeleted();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '删除批次失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-5 py-7 sm:px-8">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-2 rounded-full border border-border bg-card/60 px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-3.5" /> 返回
      </button>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-[10px] font-semibold tracking-[0.2em] text-gold">
            REVIEW
          </p>
          <h1 className="font-display mt-2 text-3xl font-semibold text-foreground">
            {batch
              ? `${batch.import_type === 'SCREENSHOT' ? '截图导入' : '手动录入'} · ${STATUS_LABEL[batch.status] ?? batch.status}`
              : '导入审阅'}
          </h1>
          {batch && (
            <p className="mt-2 text-xs text-muted-foreground">
              账户 #{batch.account_id} · 识别 {batch.items_detected} 条 · 图片{' '}
              {batch.image_count} 张
            </p>
          )}
        </div>
        <Button
          variant="outline"
          className="rounded-xl"
          onClick={() => detail.reload()}
        >
          <RefreshCw className={detail.loading ? 'animate-spin' : ''} /> 刷新
        </Button>
      </div>

      {batch?.error_message && (
        <p className="mt-4 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
          {batch.error_message}
        </p>
      )}

      {detail.loading && !batch ? (
        <p className="mt-8 flex items-center gap-2 text-sm text-text-faint">
          <RefreshCw className="size-4 animate-spin text-primary" /> 正在读导入批次…
        </p>
      ) : detail.error && !batch ? (
        <p className="mt-8 text-sm text-destructive">{detail.error}</p>
      ) : pending ? (
        <section className="mt-6 rounded-[24px] border border-border bg-card/75 px-5 py-10 text-center">
          <RefreshCw className="mx-auto size-6 animate-spin text-primary" />
          <p className="mt-3 text-sm font-medium text-foreground">正在识别截图…</p>
          <p className="mt-1 text-xs text-text-faint">
            后台 worker 解析完成后会自动刷新，通常只需要几秒。
          </p>
        </section>
      ) : batch ? (
        <>
          <div className="mt-4 space-y-3">
            {(batch.items ?? []).map((item) => (
              <ImportItemCard
                key={`${item.id}:${item.market_value}:${item.user_action ?? ''}:${item.matched_fund_code ?? ''}`}
                token={token}
                importId={importId}
                item={item}
                editable={batch.status === 'REVIEW_REQUIRED'}
                onUpdated={() => detail.reload()}
              />
            ))}
          </div>

          {batch.status === 'REVIEW_REQUIRED' && (
            <section className="mt-4 rounded-[24px] border border-border bg-card/75 p-5">
              {result && (
                <p className="mb-3 rounded-xl bg-primary/[0.06] px-3 py-2 text-xs text-primary">
                  {result}
                </p>
              )}
              {problem && (
                <p className="mb-3 rounded-xl border border-destructive/20 bg-destructive/[0.05] px-3 py-2 text-xs text-destructive">
                  {problem}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button
                  className="h-10 rounded-xl"
                  disabled={busy}
                  onClick={() => void confirm()}
                >
                  {busy ? <RefreshCw className="animate-spin" /> : null} 确认导入{' '}
                  {eligible} 条
                </Button>
                <Button
                  variant="outline"
                  className="h-10 rounded-xl text-destructive"
                  disabled={busy}
                  onClick={() => void removeBatch()}
                >
                  取消并删除该批次
                </Button>
              </div>
              <p className="mt-3 text-[10px] leading-5 text-text-faint">
                确认后按“覆盖当前快照”写入，并记一条 IMPORT_ADJUSTMENT
                审计记录；系统不会据此推断买卖流水。
              </p>
            </section>
          )}

          {batch.status === 'APPLIED' && (
            <section className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[24px] border border-primary/15 bg-primary/[0.05] p-5">
              <p className="text-sm text-primary">
                该批次已导入 {batch.items_confirmed} 条持仓并生效。
              </p>
              <Button className="h-9 rounded-xl" onClick={onOpenPortfolio}>
                返回持仓
              </Button>
            </section>
          )}
        </>
      ) : null}
    </div>
  );
}

function ImportItemCard({
  token,
  importId,
  item,
  editable,
  onUpdated,
}: {
  token: string;
  importId: string;
  item: ImportItem;
  editable: boolean;
  onUpdated: () => void;
}) {
  const [marketValue, setMarketValue] = useState(
    item.market_value == null ? '' : String(item.market_value),
  );
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');
  const skipped =
    (item.user_action ??
      (item.validation_status === 'error' ? 'SKIP' : 'UPDATE')) === 'SKIP';

  async function save(payload: {
    market_value?: number | null;
    user_action?: string;
    fund_code?: string;
  }) {
    setBusy(true);
    setProblem('');
    try {
      await updateImportItem(token, importId, item.id, payload);
      onUpdated();
    } catch (error) {
      setProblem(error instanceof Error ? error.message : '保存失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className={`rounded-[24px] border border-border bg-card/75 p-5 ${
        skipped ? 'opacity-60' : ''
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-foreground">
            {item.matched_fund_name ?? item.raw_fund_name ?? '未识别基金'}
          </p>
          <p className="mt-1 text-[11px] text-text-faint">
            {item.matched_fund_code ?? '无代码'} · 置信度{' '}
            {typeof item.confidence === 'number'
              ? `${Math.round(item.confidence * 100)}%`
              : '--'}
            {item.matched_fund_name &&
            item.raw_fund_name &&
            item.matched_fund_name !== item.raw_fund_name
              ? ` · 截图 ${item.raw_fund_name}`
              : ''}
          </p>
        </div>
        {(item.validation_issues ?? []).length > 0 && (
          <div className="flex flex-wrap gap-1">
            {(item.validation_issues ?? []).map((issue) => (
              <span
                key={issue}
                className={`rounded-full px-2 py-0.5 text-[10px] ${
                  item.validation_status === 'error'
                    ? 'bg-destructive/10 text-destructive'
                    : 'bg-gold/10 text-gold'
                }`}
              >
                {ISSUE_LABEL[issue] ?? issue}
              </span>
            ))}
          </div>
        )}
      </div>

      {!item.matched_fund_code && (item.candidates ?? []).length > 0 && editable && (
        <div className="mt-3 flex flex-wrap gap-2">
          {item.candidates?.map((candidate) => (
            <button
              key={candidate.fund_code}
              type="button"
              disabled={busy}
              onClick={() => void save({ fund_code: candidate.fund_code })}
              className="rounded-full border border-border bg-background/50 px-3 py-1 text-[11px] text-text-soft hover:border-primary/30 hover:text-primary"
            >
              {candidate.fund_code} {candidate.fund_name}
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 grid grid-cols-3 gap-3 rounded-xl bg-secondary/25 px-3 py-2 text-xs">
        <div>
          <p className="text-[10px] text-text-faint">当前持仓</p>
          <p className="mt-0.5 tabular-nums text-text-soft">
            {formatMoney(item.current_market_value)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-text-faint">本次识别</p>
          <p className="mt-0.5 tabular-nums text-foreground">
            {formatMoney(item.market_value)}
          </p>
        </div>
        <div>
          <p className="text-[10px] text-text-faint">导入后</p>
          <p className="mt-0.5 tabular-nums text-primary">
            {formatMoney(skipped ? item.current_market_value : item.market_value)}
          </p>
        </div>
      </div>

      <p className="mt-2 text-[11px] text-text-faint">
        持有收益 {formatSignedMoney(item.profit_loss)} · 持有收益率{' '}
        {formatReturn(item.profit_loss_rate, { points: true })}
      </p>

      {editable && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <label className="block min-w-44 flex-1 text-xs text-muted-foreground">
            修正持有金额
            <Input
              inputMode="decimal"
              value={marketValue}
              onChange={(event) => setMarketValue(event.target.value)}
              className="mt-1.5 h-9 rounded-xl bg-background/60"
            />
          </label>
          <Button
            variant="outline"
            className="h-9 rounded-xl text-xs"
            disabled={busy}
            onClick={() => {
              if (marketValue.trim() !== '' && Number.isNaN(Number(marketValue))) {
                setProblem('修正持有金额需为数字');
                return;
              }
              void save({
                market_value:
                  marketValue.trim() === '' ? null : Number(marketValue),
              });
            }}
          >
            保存修正
          </Button>
          <Button
            variant={skipped ? 'default' : 'outline'}
            className="h-9 rounded-xl text-xs"
            disabled={busy}
            onClick={() =>
              void save({ user_action: skipped ? 'UPDATE' : 'SKIP' })
            }
          >
            {skipped ? '改为导入' : '跳过这条'}
          </Button>
        </div>
      )}
      {problem && <p className="mt-2 text-xs text-destructive">{problem}</p>}
    </section>
  );
}
