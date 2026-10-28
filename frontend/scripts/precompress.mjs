/**
 * 构建期预压缩（第 179 期）：给 `dist/assets/**` 生成 `.gz` 与 `.br` 旁路文件。
 *
 * 为什么：静态资源没有预压缩时，每个 JS/CSS/MJS 请求都要服务端**现压** ——
 * 路线图实测 1.28 MB 主 JS gzip 一次 78 ms（identity 只要 19 ms）。首屏二十来个 chunk
 * 叠加，在单 worker 的 NAS 上是实实在在的首屏成本。
 *
 * ⚠️ 浏览器只在**安全上下文**的 `Accept-Encoding` 里报 `br`：本项目默认以
 * `http://<NAS>:8992` 部署，HTTP 下客户端只说 `gzip, deflate`。所以**真正生效的是 `.gz`**
 * （把「每请求现压」换成「读现成文件」）；`.br` 是留给将来上 HTTPS / 反代的部署，
 * 不生效也没有代价（每个文件多占几百字节到 1/4 的体积）。
 *
 * ⚠️ 只压 `assets/` 下的构建产物：`index.html` 与 `sw.js` 由后端**专用路由**提供
 * （`server.index` / `server.service_worker`，各带自己的缓存语义），给它们生成旁路文件
 * 只会留下一份没人读的死文件。字体（woff2）已经压过，不碰。
 */
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { brotliCompressSync, constants as zlibConstants, gzipSync } from 'node:zlib'

/** 值得预压缩的扩展名（与后端 `server._COMPRESSIBLE_EXTS` 对应；后端是选用的判据） */
const EXTS = new Set(['.js', '.mjs', '.css', '.svg', '.json', '.webmanifest', '.map', '.txt', '.wasm'])
/** 太小的文件压了反而更大（也省不下一次 RTT 的量级）—— 与 GZipMiddleware 的门槛同一考虑 */
const MIN_BYTES = 1024

const dist = resolve(process.argv[2] ?? 'dist')
const assets = join(dist, 'assets')

let files = 0
let gzBytes = 0
let brBytes = 0
try {
  for (const name of readdirSync(assets)) {
    const full = join(assets, name)
    const st = statSync(full)
    if (!st.isFile()) continue
    const dot = name.lastIndexOf('.')
    const ext = dot >= 0 ? name.slice(dot).toLowerCase() : ''
    if (!EXTS.has(ext) || st.size < MIN_BYTES) continue
    const buf = readFileSync(full)
    const gz = gzipSync(buf, { level: 9 })
    const br = brotliCompressSync(buf, {
      params: { [zlibConstants.BROTLI_PARAM_QUALITY]: 11 },
    })
    writeFileSync(`${full}.gz`, gz)
    writeFileSync(`${full}.br`, br)
    files += 1
    gzBytes += gz.length
    brBytes += br.length
  }
} catch (e) {
  // `assets/` 不存在 = 构建产物还没生成；这不该静默通过（否则镜像里没有旁路文件，
  // 而服务端只会在「选不到预压缩件」时回落现压 —— 表现为「优化没生效」，很难查）。
  console.error(`[precompress] 失败：${e instanceof Error ? e.message : e}`)
  process.exit(1)
}

console.log(
  `[precompress] ${files} 个文件 → gzip ${(gzBytes / 1024).toFixed(0)} KB / brotli ${(brBytes / 1024).toFixed(0)} KB`,
)
