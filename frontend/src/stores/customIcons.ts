import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, type CustomIcon } from '@/lib/api'

/**
 * 自定义图标（第 216 期）。
 *
 * 后端只回 SVG 的 `path d` 片段；这里重新拼成 `<path d="…"/>` 交给内置同一条
 * `Icon` 渲染路径（`v-html` 的内容只来自这些 d 字符串，不含脚本 / 外链）。
 * 图标是全局资源（库图标选择器与侧栏都要用），故按需加载一次并缓存。
 */
function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
    .replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

export const useCustomIconsStore = defineStore('customIcons', () => {
  const items = ref<CustomIcon[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  let inflight: Promise<void> | null = null

  async function load(force = false): Promise<void> {
    if (inflight) return inflight
    if (loaded.value && !force) return
    loading.value = true
    error.value = ''
    inflight = (async () => {
      try {
        items.value = (await api.customIcons()).items
        loaded.value = true
      } catch (e) {
        error.value = e instanceof Error ? e.message : '自定义图标加载失败'
      } finally {
        loading.value = false
        inflight = null
      }
    })()
    return inflight
  }

  function ensureLoaded(): void {
    if (!loaded.value && !loading.value) void load()
  }

  const byKey = computed<Record<string, CustomIcon>>(() => {
    const out: Record<string, CustomIcon> = {}
    for (const it of items.value) out[it.key] = it
    return out
  })

  /** 图标 key → 可用于 `Icon` 的 `<path>` 标记；不是自定义图标返回空串。 */
  function pathOf(key: string): string {
    const it = byKey.value[key]
    if (!it) return ''
    return it.paths.map((d) => `<path d="${escapeAttr(d)}"/>`).join('')
  }

  const keys = computed(() => items.value.map((it) => it.key))

  async function create(name: string, svg: string): Promise<CustomIcon> {
    const it = await api.createCustomIcon(name, svg)
    items.value = [...items.value, it]
    loaded.value = true
    return it
  }

  async function remove(key: string): Promise<void> {
    await api.deleteCustomIcon(key)
    items.value = items.value.filter((it) => it.key !== key)
  }

  return { items, loaded, loading, error, load, ensureLoaded, pathOf, keys, create, remove, byKey }
})
