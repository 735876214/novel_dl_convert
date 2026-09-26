<script setup lang="ts">
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'

/**
 * 首屏「还没有书库」提示条（第 38 期）。
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
  <div
    v-if="library.hasNoLibraries"
    class="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-border bg-card/50 px-4 py-3"
  >
    <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
      <Icon name="library" class="h-4 w-4" />
    </span>
    <div class="min-w-0 flex-1">
      <div class="text-[13px] font-semibold text-foreground">还没有书库</div>
      <p class="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
        下面的数字全是 0，是因为书还没有地方可放。新建一个书库并指定它的来源目录，
        之后的下载、上传与投递才会被接收。
      </p>
    </div>
    <Button size="sm" variant="primary" @click="createLibrary">新建书库</Button>
  </div>
</template>
