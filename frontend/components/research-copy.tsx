'use client';

import { useMemo, useState } from 'react';
import { BookOpenText, FileSearch } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { type ResearchCitations } from '@/lib/api';
import { MarkdownText } from '@/components/markdown-text';

const SUPERSCRIPT = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷', '⁸', '⁹'];

function superscript(value: number): string {
  return String(value)
    .split('')
    .map((digit) => SUPERSCRIPT[Number(digit)] ?? '')
    .join('');
}

function renderCitations(content: string, citations?: ResearchCitations | null) {
  if (!citations?.citations.length) return content;
  const numbers = new Map(
    citations.citations.map((item) => [item.evidence_id, item.number]),
  );
  return content
    .split(/(```[\s\S]*?```)/g)
    .map((part) => {
      if (part.startsWith('```')) return part;
      return part.replace(/\[(ev_[0-9a-f]+)\]/g, (_match, evidenceId: string) => {
        const number = numbers.get(evidenceId);
        return number ? superscript(number) : '';
      });
    })
    .join('');
}

function EvidenceDialog({
  citations,
  open,
  onOpenChange,
}: {
  citations: ResearchCitations;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { audit } = citations;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[86vh] flex-col gap-0 overflow-hidden rounded-[24px] border-border bg-card p-0 sm:max-w-2xl">
        <DialogHeader className="border-b border-border px-6 py-5">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-xl bg-primary/[0.08] text-primary">
              <FileSearch className="size-5" />
            </span>
            <div>
              <DialogTitle className="font-display text-xl">
                证据与核对
              </DialogTitle>
              <DialogDescription className="mt-1">
                {citations.citations.length} 条引用 · {audit.matched} 处可核对 ·{' '}
                {audit.unknown} 处无法核对
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="space-y-2.5">
            {citations.citations.map((item) => (
              <div
                key={item.evidence_id}
                className="rounded-2xl border border-border bg-card/60 p-4"
              >
                <div className="flex items-start gap-3">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-primary/[0.08] text-xs font-semibold text-primary">
                    {item.number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-foreground">
                        {item.label}
                      </p>
                      {item.fund_codes.map((code) => (
                        <span
                          key={code}
                          className="rounded-full bg-secondary px-2 py-0.5 text-[10px] text-text-soft"
                        >
                          {code}
                        </span>
                      ))}
                      {item.as_of && (
                        <span className="text-[10px] text-text-faint">
                          数据日期 {item.as_of}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 line-clamp-3 text-xs leading-6 text-muted-foreground">
                      {item.excerpt}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {citations.coverage.length > 0 && (
            <section className="mt-6">
              <p className="text-[10px] font-semibold tracking-[0.18em] text-muted-foreground">
                研究范围
              </p>
              <ul className="mt-2 space-y-1.5 text-xs leading-6 text-text-soft">
                {citations.coverage.map((line) => (
                  <li key={line} className="flex gap-2">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-primary/50" />
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {citations.sources.length > 0 && (
            <section className="mt-5">
              <p className="text-[10px] font-semibold tracking-[0.18em] text-muted-foreground">
                来源核对
              </p>
              <ul className="mt-2 space-y-1.5 text-xs leading-6 text-text-soft">
                {citations.sources.map((line) => (
                  <li key={line} className="flex gap-2">
                    <span className="mt-2 size-1 shrink-0 rounded-full bg-gold/60" />
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {audit.uncited_lines > 0 && (
            <p className="mt-5 rounded-xl bg-accent/60 px-3 py-2 text-[11px] leading-5 text-accent-foreground">
              另有 {audit.uncited_lines} 行含数字但未带引用；这是启发式统计，不代表编造。
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function ResearchCopy({
  content,
  citations,
  token,
}: {
  content: string;
  citations?: ResearchCitations | null;
  token: string;
}) {
  const [open, setOpen] = useState(false);
  const rendered = useMemo(
    () => renderCitations(content, citations),
    [content, citations],
  );
  return (
    <>
      <MarkdownText content={rendered} token={token} />
      {citations?.citations.length ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-3 inline-flex items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/25 hover:text-primary"
        >
          <BookOpenText className="size-3.5" />
          证据 {citations.citations.length} 条 · 查看
        </button>
      ) : null}
      {citations ? (
        <EvidenceDialog
          citations={citations}
          open={open}
          onOpenChange={setOpen}
        />
      ) : null}
    </>
  );
}
