<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'

/**
 * 首屏「还没有书库」引导卡（第 38 期）。
 *
 * 仪表盘在 0 库时会照常渲染全部部件，结果是首屏一排 `0 书籍 / 0 作者 / 0 系列 /
 * 0 B 占用`、`阅读目标 0%`、三行「这一行暂时没有书」，**通篇没有「书库」二字**
 * —— 用户看不出自己该先做一件事，只看出「这东西是空的」。
 *
 * 这些 0 **都是真数字**，一个都不改（改掉或藏起来才是做假）；问题不在数字，
 * 在于缺一句「为什么都是 0、先做什么」。所以这里只**补一条**提示，压在部件之上。
 *
 * ⚠️ 不注册成 `WIDGET_META` 部件：那套注册表带自定义面板、开关与布局持久化，
 * 用户一旦把这条关掉，首屏就又回到「什么都没有」；它也不该和阅读部件并列被统计。
 *
 * 第 82 期：卡片样式对齐上游（大圆角 + 主色描边 + 半透底 + 轻毛玻璃 + 径向光晕）。
 */
const library = useLibraryStore()
const wizard = useLibraryWizardStore()

function createLibrary(): void {
  // 就地弹窗（第 55 期）：不再跳设置页的新建弹窗 —— 建库这件事
  // 在哪儿发生，向导就在哪儿打开
  void wizard.show()
}
</script>

<template>
  <div v-if="library.hasNoLibraries" class="flex justify-center">
    <div
      class="relative w-full max-w-md overflow-hidden rounded-2xl border border-primary/40 bg-card/30 px-6 py-9 text-center shadow-sm backdrop-blur-[1px]"
    >
      <div
        class="pointer-events-none absolute inset-x-0 top-0 h-32"
        style="background: radial-gradient(ellipse 80% 60% at 50% -10%, color-mix(in oklch, var(--primary) 18%, transparent), transparent 70%)"
      />

      <div class="relative flex flex-col items-center">
        <div class="flex h-14 w-14 items-center justify-center rounded-lg border border-border bg-background shadow-sm">
          <Icon name="library" class="h-6 w-6 text-foreground" />
        </div>

        <h2 class="mb-2 mt-4 text-lg font-bold tracking-tight text-foreground">还没有书库</h2>
        <p class="mb-6 max-w-xs text-sm leading-relaxed text-muted-foreground">
          下面的数字全是 0，是因为书还没有地方可放。新建一个书库并指定它的来源目录，
          之后的下载、上传与投递才会被接收。
        </p>

        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-md bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          @click="createLibrary"
        >
          <Icon name="plus" class="h-4 w-4" />
          新建书库
        </button>
      </div>
    </div>
  </div>
</template>
