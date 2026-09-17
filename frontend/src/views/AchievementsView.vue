<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type AchievementItem, type AchievementsOverview } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 成就页（单用户口径，对应上游 `/achievements`）。
 *
 * 两条语义需要说清楚：
 *   · 进度由后端**实时计算**，不落库（删了书进度会变，但已解锁的不变）；
 *   · **解锁只增不退** —— 曾经达成过就是达成过，不因为书被删掉而回收。
 *
 * ⚠️ 当前成就目录是**起步集**（`core/achievements.py` 的 `ACHIEVEMENTS`），
 * 条目名与阈值待定。本页保证的是「目录 → 判定 → 解锁 → 展示」这条链路可用。
 */
const ui = useUiStore()
const data = ref<AchievementsOverview | null>(null)
const loading = ref(true)
const busy = ref(false)

const GROUP_LABELS: Record<string, string> = {
  LIBRARY: '书库',
  READING: '阅读',
  ANNOTATION: '批注',
}

const grouped = computed(() => {
  const d = data.value
  if (!d) return []
  return d.groups.map((g) => ({
    ...g,
    label: GROUP_LABELS[g.group] ?? g.group,
    items: d.items.filter((i) => i.group === g.group),
  }))
})

const pct = computed(() => {
  const d = data.value
  if (!d || !d.total) return 0
  return Math.round((d.unlocked / d.total) * 100)
})

async function load(): Promise<void> {
  loading.value = true
  try {
    data.value = await api.achievements()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '成就加载失败')
  }
  loading.value = false
}

async function backfill(): Promise<void> {
  if (!window.confirm('重算全部成就？会按当前数据重新判定，并把解锁时间重置为此刻。')) return
  busy.value = true
  try {
    const r = await api.backfillAchievements()
    data.value = r
    ui.toast(`已重算：${r.unlocked} / ${r.total} 项解锁`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '重算失败')
  } finally {
    busy.value = false
  }
}

/** 进度可能是小数（小时 / GB），整数则不带小数点 */
function fmtNum(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

function dateOf(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function itemOf(i: AchievementItem): string {
  return `${fmtNum(i.progress)} / ${fmtNum(i.target)}`
}

onMounted(load)
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <PageHead
        title="成就"
        :desc="
          data && !data.enabled
            ? '已关闭'
            : data
              ? `已解锁 ${data.unlocked} / ${data.total} 项`
              : '加载中…'
        "
      />
      <!-- 关闭时不显示「重算」：后端此时也不执行回填，按钮留着只会产生一个空动作 -->
      <Button
        v-if="data?.enabled !== false"
        size="sm"
        class="ml-auto"
        :disabled="busy"
        @click="backfill"
      >
        {{ busy ? '重算中…' : '重算成就' }}
      </Button>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <!-- 关闭态：明确说明「关闭期间不统计」，并给出开启入口 -->
    <Card v-else-if="data && !data.enabled" padding="none">
      <div class="flex flex-wrap items-center gap-3 px-4 py-4">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
          <Icon name="star" class="h-4 w-4" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">成就已关闭</div>
          <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
            关闭期间<strong>不判定、不解锁</strong>（避免出现「趁关着时偷偷解锁」的成就），
            侧栏也不再显示成就入口。已解锁的记录不会丢失，重新开启后照常显示。
          </div>
        </div>
        <RouterLink to="/settings/account/profile">
          <Button size="sm" variant="primary">去开启</Button>
        </RouterLink>
      </div>
    </Card>

    <template v-else-if="data">
      <Card class="mb-4" padding="sm">
        <div class="flex items-center gap-3">
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-primary/12 text-primary">
            <Icon name="star" class="h-4 w-4" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2">
              <span class="text-[13px] font-semibold text-foreground">总进度</span>
              <span class="text-[11.5px] text-muted-foreground">
                {{ data.unlocked }} / {{ data.total }}（{{ pct }}%）
              </span>
            </div>
            <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div class="h-full rounded-full bg-primary transition-[width] duration-500" :style="{ width: `${pct}%` }" />
            </div>
          </div>
        </div>
      </Card>

      <div v-for="g in grouped" :key="g.group" class="mb-4">
        <div class="mb-2 flex items-baseline gap-2 px-0.5">
          <h3 class="text-[13px] font-semibold text-foreground">{{ g.label }}</h3>
          <span class="font-mono text-[11px] text-muted-foreground">{{ g.group }}</span>
          <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">
            {{ g.unlocked }} / {{ g.total }}
          </span>
        </div>

        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Card
            v-for="i in g.items"
            :key="i.key"
            padding="sm"
            :class="i.unlocked ? '' : 'opacity-70'"
          >
            <div class="flex items-start gap-2.5">
              <span
                class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full"
                :class="i.unlocked ? 'bg-success/14 text-success' : 'bg-muted text-muted-foreground'"
              >
                <Icon :name="i.unlocked ? 'check' : 'star'" class="h-3.5 w-3.5" />
              </span>
              <div class="min-w-0 flex-1">
                <div class="truncate text-[12.5px] font-medium text-foreground">{{ i.name }}</div>
                <div class="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{{ i.desc }}</div>

                <div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    class="h-full rounded-full transition-[width] duration-500"
                    :class="i.unlocked ? 'bg-success' : 'bg-primary'"
                    :style="{ width: `${i.percent}%` }"
                  />
                </div>
                <div class="mt-1 flex items-baseline gap-2 text-[11px]">
                  <span class="font-mono text-foreground tabular-nums">{{ itemOf(i) }}</span>
                  <span class="font-mono text-muted-foreground">{{ i.metric }}</span>
                  <span v-if="i.unlocked" class="ml-auto text-success">
                    {{ dateOf(i.unlocked_at) }}
                  </span>
                  <span v-else class="ml-auto text-muted-foreground">{{ i.percent }}%</span>
                </div>
                <!-- metric 打错字时暴露出来，而不是静默显示 0 -->
                <div v-if="!i.known_metric" class="mt-1 text-[10.5px] text-destructive">
                  度量名 `{{ i.metric }}` 不存在，请检查目录定义
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <Card class="mt-4" padding="sm">
        <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
          <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            进度由后端实时计算、不落库；<strong>解锁只增不退</strong>——曾经达成过就是达成过，
            不因为删掉书而回收。当前成就目录是起步集，条目与阈值待定（见
            <span class="font-mono">core/achievements.py</span> 的 ACHIEVEMENTS）。
          </span>
        </div>
      </Card>
    </template>

    <EmptyState v-else icon="star" title="成就加载失败" desc="请稍后重试，或检查后端日志。" />
  </div>
</template>
