import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type FontItem } from '@/lib/api'
import { customFontFamily } from '@/lib/fonts'

/**
 * 阅读字体 store：后端字体列表 + `@font-face` 注入。
 *
 * 为什么用 store 而不是纯模块：字体要出现在**多处**（阅读器设置面板、
 * 两个设置页），任何一处上传/删除后，其它处必须立刻看到。
 */

/** 注入 @font-face 用的 <style> 元素 id */
const STYLE_ID = 'nf-user-fonts'

export const useFontsStore = defineStore('fonts', () => {
  const items = ref<FontItem[]>([])
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  const maxBytes = ref(50 * 1024 * 1024)
  const maxCount = ref(200)

  /**
   * 注册 @font-face。
   * ⚠️ `src` 必须带 `?token=`：字体是浏览器原生发起的请求，**带不了 Authorization 头**
   * （与 /cover 同一约束，见 server._MEDIA_TOKEN_PATHS）。
   */
  function injectFontFaces(list: FontItem[]): void {
    let el = document.getElementById(STYLE_ID) as HTMLStyleElement | null
    if (!el) {
      el = document.createElement('style')
      el.id = STYLE_ID
      document.head.appendChild(el)
    }
    let token = ''
    try {
      token = localStorage.getItem('nf_token') || ''
    } catch {
      /* 隐私模式 */
    }
    const q = token ? `?token=${encodeURIComponent(token)}` : ''
    const blocks: string[] = []
    for (const f of list) {
      const src = `/api/fonts/${encodeURIComponent(f.id)}/file${q}`
      // 1) 每个文件仍注册一个「按 id 命名」的 family —— 兼容旧的 `custom:<id>` 偏好
      //    （旧偏好只命中单个文件，无同族变体可用，行为等同改造前）。
      blocks.push(
        `@font-face{font-family:'${customFontFamily(f.id)}';` +
          `src:url('${src}');font-display:swap}`,
      )
      // 2) 若解析出了族（family_key），再注册一个「按族命名」的 family，并带上
      //    font-weight / font-style —— 同一族的所有变体共享此 family，浏览器据此在
      //    阅读器套用「加粗 / 斜体」时自动挑中真实变体文件，而非合成。
      if (f.family_key) {
        const fam = customFontFamily(f.family_key)
        const w = f.weight ?? 400
        const style = f.italic ? 'italic' : 'normal'
        blocks.push(
          `@font-face{font-family:'${fam}';src:url('${src}');` +
            `font-weight:${w};font-style:${style};font-display:swap}`,
        )
      }
    }
    el.textContent = blocks.join('\n')
  }

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const r = await api.fonts()
      items.value = r.items
      maxBytes.value = r.max_bytes
      maxCount.value = r.max_count
      injectFontFaces(items.value)
      loaded.value = true
      error.value = ''
    } catch (e) {
      error.value = e instanceof Error ? e.message : '字体列表加载失败'
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File): Promise<FontItem> {
    const item = await api.uploadFont(file)
    await load(true)
    return item
  }

  async function remove(id: string): Promise<void> {
    await api.deleteFont(id)
    await load(true)
  }

  return { items, loaded, loading, error, maxBytes, maxCount, load, upload, remove, injectFontFaces }
})
