<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import { statusMeta } from '@/lib/format'
import type { TaskStatus } from '@/data/tasks'
import type { TaskItem } from '@/lib/api'
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

const tasks = useTasksStore()
const ui = useUiStore()
const router = useRouter()

const GROUPS: Array<{ status: TaskStatus; title: string }> = [
  { status: 'running', title: '进行中' },
  { status: 'queued', title: '排队中' },
  { status: 'done', title: '已完成' },
  { status: 'failed', title: '失败' },
]

const grouped = computed(() =>
  GROUPS.map((g) => ({ ...g, items: tasks.tasks.filter((t) => t.status === g.status) })).filter(
    (g) => g.items.length > 0,
  ),
)

function meta(t: TaskItem) {
  return statusMeta(t.status)
}

const DOT: Record<string, string> = {
  run: 'bg-info',
  done: 'bg-success',
  queue: 'bg-warning',
  fail: 'bg-destructive',
}

function goAll(): void {
  ui.setDrawer(false)
  router.push('/tasks')
}
</script>

<template>
  <!-- 滑出抽屉：脱离文档流，不再占主区宽度；点遮罩或 Esc 关闭 -->
  <aside
    class="fixed top-[var(--shell-gap)] right-[var(--shell-gap)] bottom-[var(--shell-gap)] z-40 flex w-[min(18.75rem,86vw)] flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-2xl backdrop-blur-md backdrop-saturate-150 transition-transform duration-[220ms] ease-out"
    :class="ui.drawerOpen ? 'translate-x-0' : 'translate-x-[calc(100%+var(--shell-gap)+4px)]'"
  >
    <div class="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3.5">
      <h3 class="text-[13px] font-semibold text-foreground">任务队列</h3>
      <!-- 这里的数据来自服务端任务表，按 2.5s 轮询刷新（不是推送），所以写「自动刷新」而非「实时」 -->
      <span class="ml-auto flex items-center gap-[0.3125rem] text-[10px] tracking-[0.04em] text-muted-foreground">
        <span
          v-if="tasks.runningCount > 0"
          class="h-1.5 w-1.5 animate-pulse rounded-full bg-success"
        />
        自动刷新
      </span>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-2.5">
      <template v-for="group in grouped" :key="group.status">
        <div class="px-0.5 pt-1 pb-1.5 text-[11px] font-semibold tracking-[0.06em] text-muted-foreground">
          {{ group.title }}（{{ group.items.length }}）
        </div>

        <div
          v-for="t in group.items"
          :key="t.id"
          class="mb-1.5 rounded-md border border-border bg-card px-2.5 py-2"
        >
          <div class="flex items-center gap-1.5">
            <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="DOT[meta(t).dot]" />
            <span class="min-w-0 truncate text-[12.5px] font-medium text-foreground">{{ t.title }}</span>
            <span class="ml-auto shrink-0 text-[11px] text-muted-foreground">{{ meta(t).text }}</span>
          </div>

          <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
            <i
              class="block h-full rounded-full transition-[width] duration-500 ease-out"
              :class="[
                meta(t).cls === 'ok' ? 'bg-success' : meta(t).cls === 'err' ? 'bg-destructive' : 'bg-primary',
                t.status === 'running' ? 'animate-pulse' : '',
              ]"
              :style="{ width: t.status === 'queued' ? '0%' : `${t.progress}%` }"
            />
          </div>

          <div v-if="t.error" class="mt-1 text-[11px] text-destructive">{{ t.error }}</div>
          <div v-else-if="t.detail" class="mt-1 truncate text-[11px] text-muted-foreground">{{ t.detail }}</div>
        </div>
      </template>

      <div v-if="!grouped.length" class="px-1 py-6 text-center text-[12px] text-muted-foreground">
        暂无任务
      </div>
    </div>

    <div class="shrink-0 border-t border-border p-2.5">
      <Button variant="ghost" block @click="goAll">查看全部任务</Button>
    </div>
  </aside>
</template>
