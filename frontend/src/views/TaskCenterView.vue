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
import { useLibraryStore } from '@/stores/library'
import { useTasksStore } from '@/stores/tasks'

/**
 * 任务中心：下载 / 转换 / 跨库移动任务的统一列表。
 *
 * 数据全部来自服务端任务表（`GET /api/tasks`），**不含任何演示数据**。
 * 进度只显示**真数字**：下载器不报细分进度，所以它运行中不给百分比（给一个精确到
 * 1% 的数字等于编造）；跨库移动逐本回调「已完成 / 总数」，运行中就该显示。
 */
const tasks = useTasksStore()
const library = useLibraryStore()

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

/** 任务类型 → 图标（`bookmove` 是「把书挪个库」，用 shelf 比 convert 贴切） */
const TYPE_ICON: Record<string, string> = {
  download: 'download',
  convert: 'convert',
  bookmove: 'shelf',
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

/**
 * 什么时候显示百分比。
 *
 * 下载器**不报**细分进度（只有一个「已开始」），所以进行中不给数字，避免伪造精确度；
 * 跨库移动不一样：它逐本回调 `已完成 / 总数`，是**真数字**，进行中就该显示。
 */
function showPct(t: TaskItem): boolean {
  if (t.type === 'bookmove') return t.status === 'running' || t.status === 'done' || t.status === 'failed'
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
          <Icon :name="TYPE_ICON[t.type] ?? 'convert'" class="h-4 w-4" />
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

    <!-- 0 库时「到探索发现发起下载」也是错的：那一步必然失败（第 38 期） -->
    <EmptyState
      v-else
      icon="task"
      title="没有符合条件的任务"
      :desc="
        library.hasNoLibraries
          ? '还没有书库 —— 下载任务要有地方落才排得进来。先去「工具 → 书库管理」新建一个书库。'
          : '换个筛选条件，或到「探索发现」发起一次下载。'
      "
    />

    <Card class="mt-4" padding="sm">
      <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          任务已落 SQLite，重启后仍可查。进度只显示真实数字：下载只报「已入队 / 已开始 /
          已结束」三个里程碑，所以运行中不给出百分比；跨库移动逐本回调「已完成 / 总数」，
          运行中就是真百分比。失败的任务需要在「探索发现」重新发起下载 ——
          本页不提供「重试」，因为任务里没有保存可重放的源数据，做成一键重试只会是假的。
        </span>
      </div>
    </Card>
  </div>
</template>
