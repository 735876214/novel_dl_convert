import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type LibraryEntity, type LibraryType } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 「新增书库」全局向导（第 55 期）。
 *
 * 之前「新建书库」一律跳 `/settings/libraries?new=1`（第 49 期口径）；本期改为
 * **在当前页就地弹窗**。`LibraryWizard` 本就自带 z-50 遮罩外壳，缺的只是各宿主
 * 页没有 `types` / `sourceRoots` / `libs` 这三份数据（此前只有书库管理页的
 * `reload()` 拉过）。所以收拢成一个全局 store：
 *
 * - `show()` 现拉 `/api/libraries` 再开浮层（数据永远新鲜，拉取失败不开、只 toast）；
 * - `created()` 关浮层并刷新全局书库实体（侧栏 / 空态 / 提示条都吃它），
 *   宿主专属的刷新走 `onCreated` 一次性回调；
 * - `?new=1` 的老入口（LibrariesView onMounted）同样改走这里，行为不变。
 *
 * ⚠️ 全局只挂**一份**（App.vue）：`LibraryWizard` 是 z-50 浮层，多处各自挂会
 * 叠两层关不掉 —— 那是 LibrariesView 第 40 期注释里就写明的互斥约定。
 */
export const useLibraryWizardStore = defineStore('libraryWizard', () => {
  const open = ref(false)
  const types = ref<{ value: LibraryType; label: string; exts: string[] }[]>([])
  const sourceRoots = ref<{ name: string; path: string }[]>([])
  const libs = ref<LibraryEntity[]>([])
  /** 拉取中（供宿主给按钮忙态）；拉取失败**不开**浮层 */
  const loading = ref(false)
  /** 宿主一次性回调（建库成功后触发，用完即弃） */
  let createdCb: ((id: string) => void) | null = null

  async function show(opts: { onCreated?: (id: string) => void } = {}): Promise<void> {
    createdCb = opts.onCreated ?? null
    const ui = useUiStore()
    loading.value = true
    try {
      const res = await api.libraries()
      types.value = res.types
      sourceRoots.value = res.source_roots ?? []
      libs.value = res.items
      open.value = true
    } catch (e) {
      // 拉取失败不开空壳浮层 —— 用户会看到一个没有类型可选的半成品向导
      createdCb = null
      ui.toast(e instanceof Error ? e.message : '书库信息加载失败')
    } finally {
      loading.value = false
    }
  }

  function close(): void {
    open.value = false
    createdCb = null
  }

  /** 建库成功：关浮层 → 刷新全局书库实体 → 触发宿主回调（有则）。 */
  async function created(id: string): Promise<void> {
    open.value = false
    const cb = createdCb
    createdCb = null
    await useLibraryStore().loadLibraries(true)
    cb?.(id)
  }

  return { open, types, sourceRoots, libs, loading, show, close, created }
})
