// 注意：React Native 的默认样式不支持服务端渲染。
// 服务端渲染出的样式，在 HTML 首次渲染与客户端首次渲染之间必须保持一致。
// web 开发者通常用 CSS 媒体查询，给客户端和服务端渲染不同样式，
// 这些做法 React Native 没有直接支持，
// 但可以借助 Nativewind 之类的样式库实现。
export function useColorScheme() {
  return 'light';
}
