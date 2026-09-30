<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import Icon from '@/components/ui/Icon.vue'
import ProgressRing from '@/components/ui/ProgressRing.vue'
import { useWidgetState } from '@/composables/useWidgetState'
import type { WidgetSize } from '@/data/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 阅读目标（对应 BookOrbit 的 ReadingGoalWidget）。
 * 已完成本数来自 /api/stats（按「已读完阈值」判定，第 40 期起可配）；目标本数本地记忆。
 * 数据未接入前（stats.data 为空）显示 0，避免闪回演示值。
 *
 * ⚠️ 卡片外壳在第 82 期上移到 `DashboardWidgetRow`，本件只负责填满卡片。
 */
defineProps<{
  /** 宽度档由部件行下发（对齐上游契约） */
  size?: WidgetSize
}>()

const stats = useStatsStore()
onMounted(() => stats.load())

/** 数据态：只读 store 的真实字段（加载中 / 失败可重试） */
const state = useWidgetState(() => ({
  loading: !stats.loaded && !stats.error,
  error: stats.error,
}))

const GOAL_KEY = 'year-goal-target'

function readTarget(): number {
  try {
    const v = Number(localStorage.getItem(GOAL_KEY))
    return Number.isFinite(v) && v > 0 ? v : 30
  } catch {
    return 30
  }
}

const target = ref(readTarget())
watch(target, (v) => {
  try {
    localStorage.setItem(GOAL_KEY, String(v))
  } catch {
    /* ignore */
  }
})

const editing = ref(false)
const draft = ref(String(target.value))
const inputEl = ref<HTMLInputElement | null>(null)

const done = computed(() => stats.data?.reading.finished ?? 0)
const remaining = computed(() => Math.max(0, target.value - done.value))
const reached = computed(() => done.value >= target.value)

async function startEdit(): Promise<void> {
  draft.value = String(target.value)
  editing.value = true
  await nextTick()
  inputEl.value?.select()
}

function commit(): void {
  const parsed = Number.parseInt(draft.value, 10)
  if (Number.isFinite(parsed) && parsed > 0) target.value = parsed
  editing.value = false
}
</script>

<template>
  <div class="flex h-full items-center gap-4 p-3">
    <template v-if="state === 'loading'">
      <div class="h-[92px] w-[92px] shrink-0 animate-pulse rounded-full bg-muted" />
      <div class="flex-1 space-y-2">
        <div class="h-3.5 w-20 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-28 animate-pulse rounded bg-muted" />
        <div class="h-2.5 w-24 animate-pulse rounded bg-muted" />
      </div>
    </template>

    <div v-else-if="state === 'error'" class="flex flex-1 items-center gap-2 text-[11.5px] text-muted-foreground">
      <span>统计加载失败</span>
      <button type="button" class="cursor-pointer text-primary hover:underline" @click="stats.load(true)">
        重试
      </button>
    </div>

    <template v-else>
    <ProgressRing :value="done" :max="target" :size="92" :thickness="9" />

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5">
        <h3 class="truncate text-[13px] font-semibold text-foreground">阅读目标</h3>
        <button
          type="button"
          class="grid h-4 w-4 cursor-pointer place-items-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-primary"
          title="修改目标"
          aria-label="修改目标"
          @click="startEdit"
        >
          <!-- 与 lib/icons.ts 的 edit 同一枚（原先这里手写了一份重复 path） -->
          <Icon name="edit" class="h-3 w-3" />
        </button>
      </div>

      <p class="mt-0.5 text-[11.5px] text-muted-foreground tabular-nums">
        已完成 {{ done }} / {{ target }} 本
      </p>

      <div v-if="editing" class="mt-1.5 flex items-center gap-1.5">
        <input
          ref="inputEl"
          v-model="draft"
          type="number"
          min="1"
          class="h-6 w-16 rounded-md border border-ring bg-card px-1.5 text-[12px] text-foreground outline-none"
          @keydown.enter="commit"
          @keydown.esc="editing = false"
        >
        <button type="button" class="cursor-pointer text-[11.5px] font-medium text-primary" @click="commit">确定</button>
      </div>
      <p v-else class="mt-1 text-[11.5px]">
        <span v-if="reached" class="text-success">已达成，超出 {{ done - target }} 本</span>
        <span v-else class="text-muted-foreground">还差 {{ remaining }} 本达成</span>
      </p>
    </div>
    </template>
  </div>
</template>
