import { computed, ref } from 'vue'

import { SECTION_KEYS } from '@/data/settingsFields'
import { api, type AppConfig, type EbookConvertCap } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 设置页服务端配置的**共享单例**。
 *
 * 为什么用模块级状态而不是每页各拉一份：
 *   设置页现在是 46 个子路由，用户在侧栏来回切换时组件会反复挂载/卸载。
 *   若每页各自 `getConfig()`，会在切换时产生大量重复请求，且「未保存的修改」
 *   会随页面卸载而丢失。集中到单例后，切换页面保留编辑状态，只在必要时重新拉取。
 *
 * 注意：`cfg` 是本地可变草稿，只有调用 `saveSection()` 才会写回服务端。
 */

const cfg = ref<AppConfig | null>(null)
const files = ref<{ config_file: string; settings_file: string; backup_dir: string }>({
  config_file: '',
  settings_file: '',
  backup_dir: '',
})
const capabilities = ref<{ ebook_convert: EbookConvertCap } | null>(null)
/** 被 settings.json 覆盖的点号键 */
const overridden = ref<string[]>([])
const saving = ref(false)
const loading = ref(false)
const loadError = ref('')

/** 同一时刻只允许一个在途请求 */
let inflight: Promise<void> | null = null

function getPath(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, k) => {
    if (acc && typeof acc === 'object') return (acc as Record<string, unknown>)[k]
    return undefined
  }, obj)
}

function setPath(obj: unknown, path: string, value: unknown): void {
  const keys = path.split('.')
  const last = keys.pop()
  if (!last) return
  let cur = obj as Record<string, unknown>
  for (const k of keys) {
    if (!cur[k] || typeof cur[k] !== 'object') cur[k] = {}
    cur = cur[k] as Record<string, unknown>
  }
  cur[last] = value
}

export function useSettingsConfig() {
  const ui = useUiStore()

  function val(path: string): string | number | boolean | undefined {
    const v = getPath(cfg.value, path)
    return typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean' ? v : undefined
  }

  function setVal(path: string, v: unknown): void {
    if (cfg.value) setPath(cfg.value, path, v)
  }

  /**
   * 拉取配置。
   * @param force 为 true 时忽略「已加载」标记强制重取（保存后、还原后使用）
   * @param silent 为 true 时失败不弹提示。用于「只是想知道某个开关状态」的调用方
   *   （如侧栏据 achievements.enabled 决定是否显示成就入口）—— 那种场景下弹
   *   「配置加载失败」既打扰用户，也会让人误以为功能坏了。
   */
  async function loadConfig(force = false, silent = false): Promise<void> {
    if (!force && cfg.value) return
    if (inflight) return inflight
    loading.value = true
    loadError.value = ''
    inflight = (async () => {
      try {
        const r = await api.getConfig()
        cfg.value = r.config
        capabilities.value = r.capabilities
        overridden.value = r.overridden ?? []
        files.value = {
          config_file: r.config_file,
          settings_file: r.settings_file,
          backup_dir: r.backup_dir,
        }
      } catch (e) {
        loadError.value = e instanceof Error ? e.message : '配置加载失败'
        if (!silent) ui.toast(loadError.value)
      } finally {
        loading.value = false
        inflight = null
      }
    })()
    return inflight
  }

  /** 只提交该分区对应的顶层键，避免把其它分区的草稿一并覆盖 */
  async function saveSection(section: string): Promise<boolean> {
    if (!cfg.value) return false
    const rec = cfg.value as unknown as Record<string, unknown>
    const patch: Record<string, unknown> = {}
    for (const k of SECTION_KEYS[section] ?? []) patch[k] = rec[k]
    saving.value = true
    try {
      await api.saveConfig(patch)
      await loadConfig(true)
      ui.toast('设置已保存')
      return true
    } catch (e) {
      ui.toast(e instanceof Error ? e.message : '保存失败')
      return false
    } finally {
      saving.value = false
    }
  }

  async function clearOverrides(): Promise<void> {
    if (!window.confirm('清除 settings.json 覆盖层？（分区里保存过的值将回到 config.yaml 的值）')) return
    try {
      await api.clearOverrides()
      ui.toast('已清除覆盖层')
      await loadConfig(true)
    } catch (e) {
      ui.toast(e instanceof Error ? e.message : '清除失败')
    }
  }

  // 忽略规则：一行一条 ↔ 数组
  const ignoreText = computed({
    get: () => (cfg.value?.watcher.ignore ?? []).join('\n'),
    set: (v: string) => {
      if (!cfg.value) return
      cfg.value.watcher.ignore = v
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean)
    },
  })

  // 域名替换：一行一条 old=new ↔ 对象
  const hostReplaceText = computed({
    get: () =>
      Object.entries(cfg.value?.network.host_replace ?? {})
        .map(([k, v]) => `${k}=${v}`)
        .join('\n'),
    set: (v: string) => {
      if (!cfg.value) return
      const out: Record<string, string> = {}
      for (const line of v.split('\n')) {
        const [k, ...rest] = line.split('=')
        if (k && rest.length) out[k.trim()] = rest.join('=').trim()
      }
      cfg.value.network.host_replace = out
    },
  })

  const calibreOk = computed(() => capabilities.value?.ebook_convert.available ?? false)

  return {
    // 状态
    cfg,
    files,
    capabilities,
    overridden,
    saving,
    loading,
    loadError,
    calibreOk,
    // 取值 / 赋值
    val,
    setVal,
    // 操作
    loadConfig,
    saveSection,
    clearOverrides,
    // 文本 ↔ 结构化 的桥接
    ignoreText,
    hostReplaceText,
  }
}
