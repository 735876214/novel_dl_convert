<script setup lang="ts">
import { computed, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Icon from '@/components/ui/Icon.vue'
import { statusMeta } from '@/lib/format'
import type { TaskStatus } from '@/data/tasks'
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

/** 任务中心：下载 / 转换任务的统一列表，含状态筛选。 */
const tasks = useTasksStore()
const ui = useUiStore()

const FILTERS: Array<{ value: TaskStatus | ''; label: string }> = [
  { value: '', label: '全部' },
  { value: 'running', label: '进行中' },
  { value: 'queued', label: '排队中' },
  { value: 'done', label: '已完成' },
  { value: 'failed', label: '失败' },
]

const filter = ref<TaskStatus | ''>('')

const list = computed(() =>
  filter.value ? tasks.tasks.filter((t) => t.status === filter.value) : tasks.tasks,
)

function countOf(v: TaskStatus | ''): number {
  return v ? tasks.countByStatus(v) : tasks.tasks.length
}

const DOT: Record<string, string> = {
  run: 'bg-info',
  done: 'bg-success',
  queue: 'bg-warning',
  fail: 'bg-destructive',
}

const BAR: Record<string, string> = {
  ok: 'bg-success',
  err: 'bg-destructive',
  '': 'bg-primary',
}
</script>

<template>
  <div>
    <PageHead title="任务中心" :desc="`${tasks.runningCount} 个待处理 · 共 ${tasks.tasks.length} 条记录`" />

    <div class="mb-4 flex flex-wrap gap-1.5">
      <button
        v-for="f in FILTERS"
        :key="f.label"
        type="button"
        :title="f.label"
        class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="filter === f.value ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'"
        @click="filter = f.value"
      >
        {{ f.label }}
        <span class="ml-1 tabular-nums opacity-70">{{ countOf(f.value) }}</span>
      </button>
    </div>

    <Card v-if="list.length" padding="none">
      <div
        v-for="t in list"
        :key="t.id"
        class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
      >
        <span
          class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted"
          :class="t.type === 'download' ? 'text-info' : 'text-primary'"
        >
          <Icon :name="t.type === 'download' ? 'download' : 'convert'" class="h-4 w-4" />
        </span>

        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="truncate text-[12.5px] font-medium text-foreground">{{ t.book }}</span>
            <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="DOT[statusMeta(t.status).dot]" />
            <span class="shrink-0 text-[11px] text-muted-foreground">{{ statusMeta(t.status).text }}</span>
          </div>
          <div class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ t.detail }}</div>

          <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
            <div
              class="h-full rounded-full transition-[width] duration-500 ease-out"
              :class="BAR[statusMeta(t.status).cls]"
              :style="{ width: `${t.progress}%` }"
            />
          </div>
        </div>

        <div class="w-24 shrink-0 text-right">
          <div class="text-[12px] font-semibold text-foreground tabular-nums">{{ Math.round(t.progress) }}%</div>
          <div class="text-[11px] text-muted-foreground">
            {{ t.status === 'running' ? t.speed : t.status === 'failed' ? '' : t.eta || '' }}
          </div>
        </div>

        <Button v-if="t.status === 'failed'" size="sm" variant="ghost" @click="ui.demo(`重试 ${t.book}`)">重试</Button>
      </div>
    </Card>

    <EmptyState v-else icon="task" title="没有符合条件的任务" desc="换个筛选条件，或到「探索发现」发起一次下载。" />
  </div>
</template>
