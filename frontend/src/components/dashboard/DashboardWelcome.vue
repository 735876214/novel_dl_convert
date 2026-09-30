<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useUiStore } from '@/stores/ui'

/**
 * 空状态：全部部件与书架行都被关闭时显示。
 * 不显示空白页 —— 给一个明确的出口（恢复默认）。
 *
 * 第 82 期：卡片样式对齐上游 `DashboardWelcome`（大圆角 + 主色描边 + 半透底 +
 * 轻毛玻璃 + 径向光晕）；⚠️ 文案同步修正 —— 自定义入口已从「右下角悬浮按钮」
 * 移到首页问候语行右侧的「自定义」按钮，原文案指向的是已经不存在的入口。
 */
const dashboard = useDashboardStore()
const ui = useUiStore()

function restore(): void {
  dashboard.reset()
  ui.toast('已恢复默认布局')
}
</script>

<template>
  <div class="flex items-center justify-center px-2 py-12">
    <div
      class="relative w-full max-w-md overflow-hidden rounded-2xl border border-primary/40 bg-card/30 px-6 py-10 text-center shadow-sm backdrop-blur-[1px]"
    >
      <!-- 径向光晕（照搬上游的装饰：主色 18% 自顶部散开） -->
      <div
        class="pointer-events-none absolute inset-x-0 top-0 h-36"
        style="background: radial-gradient(ellipse 80% 60% at 50% -10%, color-mix(in oklch, var(--primary) 18%, transparent), transparent 70%)"
      />

      <div class="relative flex flex-col items-center">
        <div class="flex h-14 w-14 items-center justify-center rounded-lg border border-border bg-background shadow-sm">
          <Icon name="dash" class="h-6 w-6 text-muted-foreground" />
        </div>

        <h2 class="mb-2 mt-4 text-lg font-bold tracking-tight text-foreground">仪表盘已清空</h2>
        <p class="mb-8 max-w-xs text-sm leading-relaxed text-muted-foreground">
          你关闭了全部部件与书架行。点右上方的「自定义」可以重新开启，或直接恢复出厂布局。
        </p>

        <button
          type="button"
          class="cursor-pointer rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          @click="restore"
        >
          恢复默认布局
        </button>
      </div>
    </div>
  </div>
</template>
