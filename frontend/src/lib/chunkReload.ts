/**
 * 懒加载 chunk 失联 ⇒ **整页重载一次**（第 152 期路由层，第 179 期收口到一处）。
 *
 * 起因：路由与部分条件组件都改成了按需加载，每个页面/组件是一个带 hash 的 chunk；而
 * `frontend/scripts/deploy.mjs` 是「先删目标目录、再整体拷贝」—— 部署那一刻开着的
 * 旧页面，点进一个**没访问过**的路由 / 打开一个没加载过的组件时，它的 chunk 已经不在
 * 服务器上了 ⇒ 动态 import 404、白屏或「点了没反应」且没有任何提示。
 * 重载会拿到新的 `index.html` 与新的 chunk，用户几乎无感。
 *
 * ⚠️ 必须防死循环：chunk 是真没了（服务端回滚 / 静态目录被清空）时无条件重载会变成
 * 刷新风暴。同一标签页 30 秒内只自动重载一次，之后返回 `false` 交给上层（控制台可见）。
 *
 * ⚠️ **判据只有这一处**：`router.onError`（路由 chunk）与 `defineAsyncComponent` 的
 * `onError`（组件 chunk）都调它 —— 别在两处各写一份正则与计时器。
 */
import { defineAsyncComponent } from 'vue'

const CHUNK_ERR_RE =
  /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk .* failed|dynamically imported module/i

let chunkReloadedAt = 0

/**
 * 是 chunk 失联就整页重载（30 秒内最多一次）。返回**是否已经重载** ——
 * 调用方据此决定要不要把错误继续抛出去。
 */
export function reloadOnChunkError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? '')
  if (!CHUNK_ERR_RE.test(msg)) return false
  const now = Date.now()
  if (now - chunkReloadedAt < 30_000) return false
  chunkReloadedAt = now
  window.location.reload()
  return true
}

/**
 * 条件组件的按需加载：`defineAsyncComponent` + 同一条 chunk 失效兜底。
 *
 * 只用在「**没有布局占位、也没有持久化标记**」的条件组件上（目前唯一一处：新建书库
 * 向导 —— 点按钮才出现的 z-50 浮层）。带布局的（设置侧栏）与带状态标记的（首次引导）
 * 一律保持静态导入：异步化的空窗会让内容区横向跳一下，而「标记已落盘、组件没加载出来」
 * 会把功能永久关掉（第 179 期评审两条实测）。
 */
export function lazyComponent<T>(loader: () => Promise<T>) {
  return defineAsyncComponent({
    // vue 的签名是 `() => Promise<Component>`，这里的泛型只是让调用点不写断言
    loader: loader as unknown as () => Promise<never>,
    onError: (err, _retry, fail) => {
      if (!reloadOnChunkError(err)) fail()
    },
  })
}
