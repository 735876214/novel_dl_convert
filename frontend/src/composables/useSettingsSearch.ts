import { ref } from 'vue'

/**
 * 设置项搜索浮层的开合状态。
 *
 * 为什么用模块级单例而不是 props：搜索入口在 `SettingsSidebar`（由 `App.vue` 渲染），
 * 浮层则挂在 `SettingsLayout` 的内容区，两者不在同一棵组件树上，用事件逐层透传要改三层。
 * 这里只承载「一个浮层是否打开」，与 `stores/ui.ts`（侧栏开合等全局 UI 状态）职责不重叠。
 */
const open = ref(false)

export function useSettingsSearch() {
  return {
    /** 浮层是否打开（供外壳渲染与 App.vue 的 ⌘K 判断） */
    open,
    openPanel(): void {
      open.value = true
    },
    closePanel(): void {
      open.value = false
    },
    togglePanel(): void {
      open.value = !open.value
    },
  }
}
