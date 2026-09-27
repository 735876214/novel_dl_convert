<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import IconButton from '@/components/ui/IconButton.vue'
import type { TaskStatus } from '@/data/tasks'
import type { TaskItem } from '@/lib/api'
import { statusMeta } from '@/lib/format'
import { useTasksStore } from '@/stores/tasks'

/**
 * 顶栏任务浮层（第 65 期）。
 *
 * ## 从抽屉改过来
 *
 * 原来是一个**右侧滑出抽屉**（`TaskDrawer.vue`：`fixed` 定位 + `App.vue` 里一层全屏
 * 遮罩 + `stores/ui.ts` 的 `drawerOpen` 全局状态）。第 65 期用户口径：
 *
 *   「任务面板样式参考现有通知的浮层，流程也参考通知的样式，点『查看全部任务』
 *     进任务中心」
 *
 * 于是整块改成与 `NotificationBell` 同款的浮层：顶栏按钮（带角标）+ 下拉面板 +
 * 底部一个「查看全部任务」。**抽屉那边的三样东西一并删了**（`App.vue` 的遮罩、
 * `ui.drawerOpen` / `toggleDrawer` / `setDrawer`）—— 撤销掉的入口不能留下没人用的
 * 状态，否则下一个人会以为「抽屉还在，只是没接上」，再塞个按钮就顺手了。
 *
 * ## 两件不能顺手改的事
 *
 * 1. **千万别把轮询一起删掉**：任务数据由 `App.vue` 启动时的 `tasks.refresh()` 拉起，
 *    之后 `stores/tasks.ts` 的 `syncPolling()` 自管（有未结束任务才轮询）。
 *    这里只**读** `tasks.tasks` / `tasks.runningCount`，打开时补拉一次。
 * 2. **角标用 `runningCount`（运行中 + 排队中）**，不是「全部任务数」——
 *    后者含已完成，数字只会越来越大，角标就失去意义了。
 */
const tasks = useTasksStore()
const router = useRouter()

const open = ref(false)
const wrap = ref<HTMLElement | null>(null)

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

function toggle(): void {
  open.value = !open.value
  if (open.value) void tasks.refresh()
}

function goAll(): void {
  open.value = false
  router.push('/tasks')
}

/** 点外部关闭 */
function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  if (wrap.value && !wrap.value.contains(e.target as Node)) open.value = false
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="wrap" class="relative">
    <!-- 图标沿用侧栏原来「任务中心」那一项的 `task`（清单形）：同一件事在顶栏与
         侧栏长得一样，用户才认得出是同一条去处的延续。 -->
    <IconButton
      label="任务"
      :active="open"
      :expanded="open"
      :badge="tasks.runningCount"
      @click.stop="toggle"
    >
      <Icon name="task" class="h-[17px] w-[17px]" />
    </IconButton>

    <!-- 浮层：点按钮切换，点外部 / Esc 关闭（与通知浮层同一套行为） -->
    <div
      v-if="open"
      class="absolute top-[calc(100%+0.5rem)] right-0 z-50 w-[min(20rem,88vw)] overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-2xl backdrop-blur-md backdrop-saturate-150"
    >
      <div class="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
        <h3 class="text-[13px] font-semibold text-foreground">任务队列</h3>
        <!-- 这里的数据来自服务端任务表，按 2.5s 轮询刷新（不是推送），所以写「自动刷新」而非「实时」 -->
        <span class="ml-auto flex items-center gap-[0.3125rem] text-[10px] tracking-[0.04em] text-muted-foreground">
          <span v-if="tasks.runningCount > 0" class="h-1.5 w-1.5 animate-pulse rounded-full bg-success" />
          自动刷新
        </span>
      </div>

      <div class="max-h-[min(24rem,60vh)] overflow-y-auto p-2.5">
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

      <div class="border-t border-border p-2">
        <Button variant="ghost" block @click.stop="goAll">查看全部任务</Button>
      </div>
    </div>
  </div>
</template>
