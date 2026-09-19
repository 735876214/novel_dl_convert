import { computed, getCurrentScope, onScopeDispose, ref } from 'vue'

/**
 * 设置页「未保存变更」上报通道。
 *
 * 设置页有两类脏状态来源：
 *   1. **服务端配置草稿**（`useSettingsConfig`）—— 由该单例自己比对基线与草稿，
 *      使用它的页自动获得脏状态，无需在此注册；
 *   2. **页面自持草稿**（如「资料」页的显示名 / 时区、「收书目录」页的自动处理开关）
 *      —— 这类页各自持有 ref 与保存逻辑，因此通过本通道把
 *      「是否脏」与「如何放弃」两个函数上报给外壳 `SettingsLayout` 统一呈现。
 *
 * 只保存**函数**而不是快照：`isDirty` 在 computed 里被调用时才能追踪到页面自己的
 * ref 依赖，从而天然保持响应式，也不必让页面再写一遍 watch。
 */
export interface SettingsDirtyEntry {
  /** 唯一键（一般用设置页 path），重复注册会覆盖前一条，避免热更后残留 */
  key: string
  /** 展示给用户的来源名，如「资料」「收书目录」 */
  label: string
  /** 当前是否有未保存改动（内部读取页面自己的响应式状态） */
  isDirty: () => boolean
  /** 放弃改动：把页面草稿恢复成已保存值 */
  discard: () => void
}

const registry = ref<SettingsDirtyEntry[]>([])

export function useSettingsDirty() {
  /** 已上报的条目（含实时脏状态） */
  const entries = computed(() =>
    registry.value.map((e) => ({ key: e.key, label: e.label, dirty: e.isDirty() })),
  )

  /** 是否存在未保存改动（服务端配置草稿不在此通道内，由外壳另行合并） */
  const hasDirty = computed(() => registry.value.some((e) => e.isDirty()))

  /** 有改动的来源名，用于提示条文案 */
  const dirtyLabels = computed(() =>
    registry.value.filter((e) => e.isDirty()).map((e) => e.label),
  )

  /**
   * 页面挂载时上报自己。组件卸载（含 KeepAlive 的 scope 销毁）时自动注销，
   * 避免离开设置页后提示条被幽灵条目一直点亮。
   */
  function register(entry: SettingsDirtyEntry): void {
    registry.value = [...registry.value.filter((e) => e.key !== entry.key), entry]
    if (getCurrentScope()) onScopeDispose(() => unregister(entry.key))
  }

  function unregister(key: string): void {
    registry.value = registry.value.filter((e) => e.key !== key)
  }

  /** 放弃全部已上报页面的改动 */
  function discardAll(): void {
    for (const e of registry.value) if (e.isDirty()) e.discard()
  }

  return { entries, hasDirty, dirtyLabels, register, unregister, discardAll }
}
