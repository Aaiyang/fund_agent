import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '持见 · 小镜',
  description: '把持仓问明白，把选择看清楚。',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
