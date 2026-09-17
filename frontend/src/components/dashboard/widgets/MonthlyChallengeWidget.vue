<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { useStatsStore } from '@/stores/stats'

/** 月度挑战：本月入库本数 vs 本地目标（可在面板外直接改，存 localStorage）。 */
const stats = useStatsStore()
onMounted(() => stats.load())

const GOAL_KEY = 'month-goal'

function readGoal(): number {
  try {
    const v = Number(localStorage.getItem(GOAL_KEY))
    return Number.isFinite(v) && v > 0 ? v : 10
  } catch {
    return 10
  }
}

const target = ref(readGoal())
watch(target, (v) => {
  try {
    localStorage.setItem(GOAL_KEY, String(v))
  } catch {
    /* ignore */
  }
})

const done = computed(() => stats.data?.added_month ?? 0)
const pct = computed(() => Math.min(100, target.value ? (done.value / target.value) * 100 : 0))
const reached = computed(() => done.value >= target.value)
</script>

<template>
  <div class="flex h-full flex-col justify-between rounded-lg border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-[13px] font-semibold text-foreground">月度挑战</h3>
      <p class="mt-1 text-[11.5px] text-muted-foreground tabular-nums">
        本月已入库 <span class="font-semibold text-foreground">{{ done }}</span> / {{ target }} 本
      </p>
    </div>

    <div class="mt-3">
      <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div class="h-full rounded-full bg-primary transition-[width]" :style="{ width: `${pct}%` }" />
      </div>
      <div class="mt-2 flex items-center justify-between">
        <span class="text-[11px]" :class="reached ? 'text-success' : 'text-muted-foreground'">
          {{ reached ? '已达成' : `还差 ${Math.max(0, target - done)} 本` }}
        </span>
        <input
          v-model.number="target"
          type="number"
          min="1"
          class="h-6 w-14 rounded-md border border-border bg-muted px-1.5 text-right text-[11.5px] text-foreground outline-none focus:border-ring"
          title="修改月度目标"
        >
      </div>
    </div>
  </div>
</template>
