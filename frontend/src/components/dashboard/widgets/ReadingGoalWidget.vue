<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import ProgressRing from '@/components/ui/ProgressRing.vue'
import { useStatsStore } from '@/stores/stats'

/**
 * 阅读目标（对应 BookOrbit 的 ReadingGoalWidget）。
 * 已完成本数来自 /api/stats（按「已读完阈值」判定，第 40 期起可配）；目标本数本地记忆。
 * 数据未接入前（stats.data 为空）显示 0，避免闪回演示值。
 */
const stats = useStatsStore()
onMounted(() => stats.load())

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
  <div class="flex h-full items-center gap-4 rounded-lg border border-border bg-card p-4 shadow-sm">
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
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-3 w-3">
            <path d="M12 20h9" />
            <path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z" />
          </svg>
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
  </div>
</template>
