import { ScrollViewStyleReset } from 'expo-router/html';
import type { ReactNode } from 'react';

// 本文件只在 web 端生效，静态渲染时用它给每个 web 页面
// 配置根 HTML。
// 这个函数里的内容只在 Node.js 环境运行，
// 访问不到 DOM 或浏览器 API。
export default function Root({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />

        {/*
          在 web 上禁用 body 滚动，这样 ScrollView 的表现才更接近原生端。
          不过移动端 web 往往更希望保留 body 滚动，想启用的话删掉这一行即可。
        */}
        <ScrollViewStyleReset />

        {/* 用裸 CSS 兜底，确保深色模式下的背景色永远不闪变。 */}
        <style dangerouslySetInnerHTML={{ __html: responsiveBackground }} />
        {/* 需要全局生效的其他 <head> 元素可以加在这里... */}
      </head>
      <body>{children}</body>
    </html>
  );
}

const responsiveBackground = `
body {
  background-color: #fff;
}
@media (prefers-color-scheme: dark) {
  body {
    background-color: #000;
  }
}`;
