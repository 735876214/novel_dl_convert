<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useUiStore } from '@/stores/ui'

/**
 * 空状态：全部部件与书架行都被关闭时显示。
 * 不显示空白页 —— 给一个明确的出口（恢复默认）。
 */
const dashboard = useDashboardStore()
const ui = useUiStore()

function restore(): void {
  dashboard.reset()
  ui.toast('已恢复默认布局')
}
</script>

<template>
  <div class="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card/50 px-6 py-16 text-center">
    <div class="grid h-12 w-12 place-items-center rounded-full bg-muted text-muted-foreground">
      <Icon name="dash" class="h-5 w-5" />
    </div>
    <h2 class="mt-4 text-[15px] font-semibold text-foreground">仪表盘已清空</h2>
    <p class="mt-1.5 max-w-[42ch] text-[12.5px] leading-relaxed text-muted-foreground">
      你关闭了全部部件与书架行。用右下角的调节按钮可以重新开启，或直接恢复出厂布局。
    </p>
    <button
      type="button"
      class="mt-5 cursor-pointer rounded-md bg-primary px-4 py-2 text-[12.5px] font-medium text-primary-foreground transition-opacity hover:opacity-90"
      @click="restore"
    >
      恢复默认布局
    </button>
  </div>
</template>
