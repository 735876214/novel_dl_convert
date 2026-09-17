<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { statusMeta } from '@/lib/format'
import type { TaskStatus } from '@/data/tasks'
import type { TaskItem } from '@/lib/api'
import { useTasksStore } from '@/stores/tasks'

/**
 * 任务中心：下载 / 转换任务的统一列表。
 *
 * 数据全部来自服务端任务表（`GET /api/tasks`），**不含任何演示数据**。
 * 进度只显示真实里程碑，因此运行中的任务不显示百分比 —— 下载器不报细分进度，
 * 给出一个精确到 1% 的数字等于编造。
 */
const tasks = useTasksStore()

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

/** 仅「已结束」的任务才显示百分比；进行中不显示（避免伪造精确度） */
function showPct(t: TaskItem): boolean {
  return t.status === 'done' || t.status === 'failed'
}

function timeOf(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

onMounted(() => {
  void tasks.refresh()
})
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <PageHead
        title="任务中心"
        :desc="`${tasks.runningCount} 个未结束 · 共 ${tasks.tasks.length} 条记录`"
      />
      <Button size="sm" class="ml-auto" :disabled="tasks.loading" @click="tasks.refresh()">刷新</Button>
    </div>

    <p v-if="tasks.error" class="mb-3 text-[11.5px] text-destructive">{{ tasks.error }}</p>

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
            <span class="truncate text-[12.5px] font-medium text-foreground">{{ t.title }}</span>
            <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="DOT[statusMeta(t.status).dot]" />
            <span class="shrink-0 text-[11px] text-muted-foreground">{{ statusMeta(t.status).text }}</span>
            <span v-if="t.actor" class="shrink-0 text-[11px] text-muted-foreground">· {{ t.actor }}</span>
            <span class="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">
              {{ timeOf(t.created_at) }}
            </span>
          </div>
          <div v-if="t.detail" class="mt-0.5 truncate text-[11px] text-muted-foreground">{{ t.detail }}</div>

          <!-- 进行中用不定量条：下载器不报细分进度，不显示百分比 -->
          <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
            <div
              class="h-full rounded-full transition-[width] duration-500 ease-out"
              :class="[BAR[statusMeta(t.status).cls], t.status === 'running' ? 'animate-pulse' : '']"
              :style="{ width: t.status === 'queued' ? '0%' : `${t.progress}%` }"
            />
          </div>

          <p v-if="t.error" class="mt-1 text-[11px] text-destructive">{{ t.error }}</p>
          <p v-else-if="t.notice" class="mt-1 text-[11px] text-muted-foreground">{{ t.notice }}</p>
        </div>

        <div class="w-16 shrink-0 text-right">
          <div v-if="showPct(t)" class="text-[12px] font-semibold text-foreground tabular-nums">
            {{ Math.round(t.progress) }}%
          </div>
          <div v-else class="text-[11px] text-muted-foreground">
            {{ t.status === 'running' ? '进行中' : '排队中' }}
          </div>
        </div>

        <a v-if="t.status === 'done' && t.result" :href="t.result" class="shrink-0">
          <Button size="sm" variant="ghost">下载</Button>
        </a>
      </div>
    </Card>

    <EmptyState
      v-else
      icon="task"
      title="没有符合条件的任务"
      desc="换个筛选条件，或到「探索发现」发起一次下载。"
    />

    <Card class="mt-4" padding="sm">
      <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          任务已落 SQLite，重启后仍可查。进度只显示真实里程碑（已入队 / 已开始 / 已结束），
          因此运行中不给出百分比。失败的任务需要在「探索发现」重新发起下载 ——
          本页不提供「重试」，因为任务里没有保存可重放的源数据，做成一键重试只会是假的。
        </span>
      </div>
    </Card>
  </div>
</template>
