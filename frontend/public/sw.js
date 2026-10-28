/*
 * Service Worker（第 153 期，对齐上游 BookOrbit 的 PWA 形态）。
 *
 * 只做两件事，刻意**不缓存业务数据**：
 *   1. 导航请求 network-first：在线永远拿最新壳；离线回退到上次成功缓存的 `/`。
 *   2. `/static/v2/assets/`（文件名带内容 hash、内容不可变）cache-first。
 *
 * 不缓存 `/api` `/ws` `/opds` `/koreader` `/download` `/health`：
 *   阅读进度、权限、书文件都必须是服务器说了算，离线缓存只会造成「看到旧数据 /
 *   退出登录后还能读到书」这类安全问题。
 *
 * 升级语义：`CACHE` 换名 → activate 时删掉所有旧缓存；导航 network-first 保证
 * 新壳先到手，不会出现「旧壳找已删 chunk」。
 */
// 第 179 期：v1 → v2。静态资源开始带 `Vary: Accept-Encoding`（预压缩件协商），
// 换一代缓存名让旧缓存整批作废一次 —— 避免「旧条目按新 Vary 匹配不上 / 或复用错编码」。
// activate 会删掉所有非当前名的缓存，用户侧无感。
const CACHE = 'nf-shell-v2'

self.addEventListener('install', () => {
  // 不等旧页面关掉：新 SW 立即接管，配合 network-first 不会发旧壳。
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys()
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return

  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return

  // 后端面一律直连，不进缓存。
  if (/^\/(api|ws|opds|koreader|download|health)(\/|$)/.test(url.pathname)) return

  // 页面导航：network-first，离线回退到缓存的壳。
  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const res = await fetch(req)
          if (res && res.ok) {
            const cache = await caches.open(CACHE)
            await cache.put('/', res.clone())
          }
          return res
        } catch {
          const cache = await caches.open(CACHE)
          const shell = await cache.match('/')
          return shell || Response.error()
        }
      })(),
    )
    return
  }

  // 带 hash 的构建产物：cache-first（名字变了就是另一份文件）。
  if (url.pathname.includes('/assets/')) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE)
        const hit = await cache.match(req)
        if (hit) return hit
        const res = await fetch(req)
        if (res && res.ok) await cache.put(req, res.clone())
        return res
      })(),
    )
  }
})
