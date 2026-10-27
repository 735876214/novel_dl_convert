/*
 * 启动前置脚本（第 153 期）。
 *
 * 为什么是**外置**文件而不是 index.html 里的内联 <script>：
 * 全局 CSP（server.py 的 `_SECURITY_HEADERS`）是 `script-src 'self'`，
 * 内联脚本会被浏览器直接拦掉（表现为「深色模式失效 + 旧书签 404」）。
 * 上游 BookOrbit 同样用 /theme-init.js 外置。
 *
 * 两件事，顺序不能换：
 *   1. 旧 hash 链接迁移：`/#/shelf` → `/shelf`（第 153 期把 hash 路由改成 history）。
 *   2. 主题预置：在首屏渲染前套 dark / accent-* / radius-*，避免 FOUC。
 */
;(function () {
  // 1) 旧 hash 链接迁移。只认 `#/` 开头，纯锚点（#top）不动。
  try {
    var h = window.location.hash
    if (h && h.charAt(1) === '/') {
      window.history.replaceState(null, '', h.slice(1) || '/')
    }
  } catch (e) {
    /* file:// 等环境没有 history 能力：保持原样即可 */
  }

  // 2) 主题预置（与 BookOrbit 的 /theme-init.js 同口径）。
  //    localStorage 键：theme（dark / light / system）、accent、radius；值均为 JSON。
  function readStoredValue(key, fallback) {
    var stored = localStorage.getItem(key)
    if (stored === null) return fallback
    try {
      return JSON.parse(stored)
    } catch (e) {
      return stored
    }
  }

  var theme = readStoredValue('theme', 'system')
  var accent = readStoredValue('accent', 'neutral')
  var radius = readStoredValue('radius', 'default')

  var systemDark =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  var isDark = theme === 'dark' || (theme !== 'light' && systemDark)

  var root = document.documentElement
  if (isDark) root.classList.add('dark')
  if (accent !== 'neutral') root.classList.add('accent-' + accent)
  if (radius !== 'default') root.classList.add('radius-' + radius)

  // 3) Service Worker（第 153 期）：统一注册在根路径 `/sw.js`。
  //    后端用 `Service-Worker-Allowed: /` 把作用域放到全站；开发期由 Vite 的
  //    public/ 直出（本身就在根）。注册失败不影响任何功能。
  try {
    if (
      'serviceWorker' in navigator &&
      (window.location.protocol === 'http:' || window.location.protocol === 'https:')
    ) {
      window.addEventListener('load', function () {
        navigator.serviceWorker.register('/sw.js').catch(function () {})
      })
    }
  } catch (e) {
    /* 隐私模式 / 老浏览器：退化为纯在线，不报错 */
  }
})()
