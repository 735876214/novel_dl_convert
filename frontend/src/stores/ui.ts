import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 外壳 UI 状态（toast）。
 *
 * ⚠️ 第 90 期删掉了 `sidebarCollapsed` / `toggleSidebar`：侧栏折叠改由
 * `ui/sidebar` 的 `SidebarProvider` 用 provide/inject 下发（`useSidebar()`），
 * 因为折叠状态还牵连抽屉态、图标条宽度、拖拽调宽三件事 —— 放在一个 Pinia
 * store 里，就得让每个消费方自己去拼「现在到底该显示成什么样」。
 * 顺带一个好处：这是个**本机**偏好（localStorage），不该跟着账号同步。
 *
 * ⚠️ 第 65 期删掉了 `drawerOpen` / `toggleDrawer` / `setDrawer`：任务面板从
 * 「右侧滑出抽屉」改成顶栏浮层（`TaskFlyout.vue`）后，浮层的开合是组件自己的
 * 局部状态（与通知浮层同款：点外部 / Esc 关闭），不再需要全局标志位。
 * 留着一个没人读写的 `drawerOpen`，只会让「再塞个抽屉按钮」变得顺手。
 */
export const useUiStore = defineStore('ui', () => {
  const toastMessage = ref('')
  let toastTimer: ReturnType<typeof setTimeout> | null = null

  /** 底部提示条；2 秒后自动隐藏（与 v2 的 toast() 一致） */
  function toast(message: string): void {
    toastMessage.value = message
    if (toastTimer !== null) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toastMessage.value = ''
      toastTimer = null
    }, 2000)
  }

  /**
   * ⚠️ 这里原本有个 `demo(label)`：给占位按钮统一打「演示动作：」前缀的 toast。
   * 第 32 期把**最后一个调用点**（侧栏「库」组的假按钮）接上真实路由后，它已无任何
   * 调用者，故删掉 —— 留着只会让「再塞个假按钮」变得顺手。
   */
  return {
    toastMessage,
    toast,
  }
})
