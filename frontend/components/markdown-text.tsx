'use client';

import { Suspense, lazy, useMemo } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { FundHoldingsCard } from '@/components/fund-holdings-card';
import { splitResearchBlocks } from '@/lib/research-blocks';

const FundAnalysisCard = lazy(() =>
  import('@/components/fund-analysis-card').then((module) => ({
    default: module.FundAnalysisCard,
  })),
);
const ResearchCard = lazy(() =>
  import('@/components/research-cards').then((module) => ({
    default: module.ResearchCard,
  })),
);

const components: Components = {
  h1: ({ children }) => (
    <h1 className="font-display mb-4 mt-2 text-2xl font-semibold tracking-tight text-foreground">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="font-display mt-7 mb-3 border-b border-border pb-2 text-xl font-semibold text-foreground">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-6 mb-2 text-[16px] font-semibold text-foreground">
      {children}
    </h3>
  ),
  h4: ({ children }) => (
    <h4 className="mt-5 mb-2 text-[15px] font-semibold text-foreground">
      {children}
    </h4>
  ),
  p: ({ children }) => <p className="my-3 leading-8">{children}</p>,
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  ul: ({ children }) => (
    <ul className="my-3 list-disc space-y-1.5 pl-5">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-3 list-decimal space-y-1.5 pl-5">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-4 rounded-r-xl border-l-2 border-primary/40 bg-primary/[0.045] px-4 py-1 text-text-soft">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-6 border-border" />,
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline decoration-primary/30 underline-offset-4"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-4 overflow-x-auto rounded-xl border border-border">
      <table className="w-full min-w-[520px] border-collapse text-left text-[13px]">
        {children}
      </table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-secondary/70">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-border px-3 py-2.5 font-semibold text-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border/70 px-3 py-2.5 align-top text-text-soft last:border-b-0">
      {children}
    </td>
  ),
  tr: ({ children }) => <tr className="even:bg-primary/[0.018]">{children}</tr>,
  pre: ({ children }) => (
    <pre className="my-4 overflow-x-auto rounded-xl bg-[#20362c] p-4 text-[12px] leading-6 text-[#dde9df]">
      {children}
    </pre>
  ),
  code: ({ className, children }) =>
    className ? (
      <code className="font-mono text-[12px]">{children}</code>
    ) : (
      <code className="rounded bg-primary/[0.08] px-1.5 py-0.5 font-mono text-[0.9em] text-primary">
        {children}
      </code>
    ),
};

function ChartSkeleton() {
  return (
    <div className="my-4 h-36 animate-pulse rounded-2xl border border-border bg-card/50" />
  );
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {content}
    </ReactMarkdown>
  );
}

export function MarkdownText({
  content,
  token,
}: {
  content: string;
  token: string;
}) {
  const blocks = useMemo(() => splitResearchBlocks(content), [content]);
  return (
    <div className="assistant-copy break-words">
      {blocks.map((block, index) => {
        if (block.kind === 'chart') {
          return (
            <Suspense
              key={`${block.fundCode}-${index}`}
              fallback={<ChartSkeleton />}
            >
              <FundAnalysisCard token={token} fundCode={block.fundCode} />
            </Suspense>
          );
        }
        if (block.kind === 'holdings') {
          return (
            <FundHoldingsCard
              key={`${block.fundCode}-holdings-${index}`}
              data={block}
            />
          );
        }
        if (
          block.kind === 'stock' ||
          block.kind === 'sector' ||
          block.kind === 'allocation'
        ) {
          return (
            <Suspense key={`research-${index}`} fallback={<ChartSkeleton />}>
              <ResearchCard token={token} card={block} />
            </Suspense>
          );
        }
        return block.content.trim() ? (
          <MarkdownBody key={`text-${index}`} content={block.content} />
        ) : null;
      })}
    </div>
  );
}
