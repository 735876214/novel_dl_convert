import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 外壳 UI 状态（toast / 任务抽屉 / 侧栏折叠 / 全局搜索）。
 *
 * 这是对计划里五个 store 的一处扩展：toast 被导航、设置、主题三处共用，
 * 抽屉与侧栏折叠属于外壳而非某个业务域，独立出来比塞进 nav store 更干净。
 */
export const useUiStore = defineStore('ui', () => {
  const toastMessage = ref('')
  let toastTimer: ReturnType<typeof setTimeout> | null = null

  const drawerOpen = ref(false)
  const sidebarCollapsed = ref(false)

  /** 底部提示条；2 秒后自动隐藏（与 v2 的 toast() 一致） */
  function toast(message: string): void {
    toastMessage.value = message
    if (toastTimer !== null) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toastMessage.value = ''
      toastTimer = null
    }, 2000)
  }

  function toggleDrawer(): void {
    drawerOpen.value = !drawerOpen.value
  }

  function setDrawer(open: boolean): void {
    drawerOpen.value = open
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
  }

  /**
   * ⚠️ 这里原本有个 `demo(label)`：给占位按钮统一打「演示动作：」前缀的 toast。
   * 第 32 期把**最后一个调用点**（侧栏「库」组的假按钮）接上真实路由后，它已无任何
   * 调用者，故删掉 —— 留着只会让「再塞个假按钮」变得顺手。
   */
  return {
    toastMessage,
    drawerOpen,
    sidebarCollapsed,
    toast,
    toggleDrawer,
    setDrawer,
    toggleSidebar,
  }
})
