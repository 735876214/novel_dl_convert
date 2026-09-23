<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import { type ReadingEvent } from '@/lib/api'
import { useActivityStore } from '@/stores/activity'

/**
 * 阅读活动（第 31 期新增）：贡献热力图 + 时间轴。
 * 视觉对齐 BookOrbit 克隆口径（冷灰中性、主色 #2563eb），纯前端确定性渲染、零外链。
 * 数据来自后端 /api/reading-activity（reading_sessions 聚合 + annotations + achievements 合并），
 * 经 stores/activity 缓存并按当前书库与范围（今年/去年/全部）拉取。
 */
const activity = useActivityStore()
const data = computed(() => activity.data)
const loading = computed(() => activity.loading)
const range = ref<'this' | 'last' | 'all'>('all')

const rangeOptions = [
  { value: 'this', label: '今年' },
  { value: 'last', label: '去年' },
  { value: 'all', label: '全部' },
]

function yearOf(r: 'this' | 'last' | 'all'): number | undefined {
  const y = new Date().getFullYear()
  if (r === 'this') return y
  if (r === 'last') return y - 1
  return undefined
}

const headDesc = computed(() => {
  if (loading.value) return '加载中…'
  if (activity.error) return '加载失败'
  const h = data.value?.heatmap
  if (!h) return '加载中…'
  return h.active_days ? '按日阅读分钟贡献与活动时间流' : '尚无阅读记录'
})

onMounted(() => void activity.load(false, yearOf(range.value)))
watch(range, () => void activity.load(true, yearOf(range.value)))

// ---------------- 热力图（GitHub 式贡献日历） ----------------
const LEVEL_COLORS = ['#eef1f5', '#c7d6f7', '#93b1f0', '#5b86e8', '#2563eb']

function isoLocal(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const calendar = computed(() => {
  const days = data.value?.heatmap.days ?? []
  const map = new Map<string, { minutes: number; sessions: number }>()
  let max = 0
  for (const d of days) {
    map.set(d.date, { minutes: d.minutes, sessions: d.sessions })
    if (d.minutes > max) max = d.minutes
  }
  const now = new Date()
  let end: Date
  let start: Date
  const r = range.value
  if (r === 'all') {
    end = now
    start = new Date(now)
    start.setDate(start.getDate() - 364)
  } else {
    const y = yearOf(r)!
    start = new Date(y, 0, 1)
    end = r === 'this' ? now : new Date(y, 11, 31)
  }
  // 对齐到周日（一周起点），整周渲染
  const s = new Date(start)
  s.setDate(s.getDate() - s.getDay())
  const cells: Array<{ date: string; minutes: number; sessions: number; future: boolean }> = []
  const cur = new Date(s)
  while (cur <= end) {
    const iso = isoLocal(cur)
    const hit = map.get(iso)
    cells.push({
      date: iso,
      minutes: hit?.minutes ?? 0,
      sessions: hit?.sessions ?? 0,
      future: cur > now,
    })
    cur.setDate(cur.getDate() + 1)
  }
  const weeks: typeof cells[] = []
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7))
  return { weeks, max }
})

function levelColor(minutes: number, max: number): string {
  if (minutes <= 0) return LEVEL_COLORS[0]
  if (max <= 0) return LEVEL_COLORS[1]
  const step = max / 4
  const lvl = Math.min(4, 1 + Math.floor(minutes / step))
  return LEVEL_COLORS[lvl]
}

function tip(c: { date: string; minutes: number; sessions: number }): string {
  return `${c.date} · ${Math.round(c.minutes)} 分钟 / ${c.sessions} 次`
}

// ---------------- 时间轴 ----------------
const grouped = computed(() => {
  const evs: ReadingEvent[] = data.value?.timeline.events ?? []
  const byDay = new Map<string, ReadingEvent[]>()
  for (const e of evs) {
    const d = new Date(e.ts * 1000)
    const key = isoLocal(d)
    if (!byDay.has(key)) byDay.set(key, [])
    byDay.get(key)!.push(e)
  }
  return [...byDay.entries()].map(([date, items]) => ({ date, items }))
})

function eventIcon(e: ReadingEvent): string {
  return e.type === 'session' ? 'clock' : e.type === 'annotation' ? 'pencil' : 'star'
}

function eventText(e: ReadingEvent): string {
  if (e.type === 'session') return `阅读《${e.title || '未知书籍'}》· ${Math.max(1, Math.round(e.seconds / 60))} 分钟`
  if (e.type === 'annotation') {
    const extra = e.note ? `：${e.note}` : e.quote ? `：「${e.quote}」` : ''
    return `在《${e.title || '未知书籍'}》留下批注${extra}`
  }
  return `解锁成就：${e.name}`
}

function hhmm(ts: number): string {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/** 时间轴上**实际渲染**的条数。后端默认只回最近 120 条，靠 `timeline.total` 才知道有没有被截断。 */
const shownCount = computed(() => grouped.value.reduce((n, g) => n + g.items.length, 0))
const timelineTotal = computed(() => data.value?.timeline.total ?? 0)

/** 「加载更多」每步 +200，上限对齐后端的 500。 */
const LOAD_MORE_STEP = 200
const TIMELINE_MAX = 500

function loadMore(): void {
  const next = Math.min(TIMELINE_MAX, activity.limit + LOAD_MORE_STEP)
  void activity.load(true, yearOf(range.value), next)
}
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <PageHead title="阅读活动" :desc="headDesc" />
      <div class="ml-auto">
        <Segment :options="rangeOptions" v-model="range" />
      </div>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="data">
      <!-- 贡献热力图 -->
      <Card class="mb-4" padding="sm">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-[13px] font-semibold text-foreground">阅读热力图</h3>
          <span class="text-[11.5px] text-muted-foreground tabular-nums">
            {{ data.heatmap.active_days }} 个活跃日 · 共 {{ Math.round(data.heatmap.total_minutes) }} 分钟
          </span>
        </div>
        <div class="overflow-x-auto">
          <div class="flex gap-[3px]">
            <div v-for="(week, wi) in calendar.weeks" :key="wi" class="flex flex-col gap-[3px]">
              <div
                v-for="(c, di) in week"
                :key="di"
                role="img"
                :aria-label="c.future ? '未来日期' : tip(c)"
                class="h-[11px] w-[11px] rounded-[2px] transition-transform duration-150 hover:scale-125 hover:ring-2 hover:ring-primary/30"
                :style="{ backgroundColor: levelColor(c.minutes, calendar.max) }"
                :title="c.future ? '' : tip(c)"
              ></div>
            </div>
          </div>
        </div>
        <div class="mt-3 flex items-center gap-1.5 text-[11px] text-muted-foreground" aria-hidden="true">
          <span>少</span>
          <span
            v-for="(col, i) in LEVEL_COLORS"
            :key="i"
            class="h-[11px] w-[11px] rounded-[2px]"
            :style="{ backgroundColor: col }"
          ></span>
          <span>多</span>
        </div>
      </Card>

      <!-- 时间轴 -->
      <Card padding="sm">
        <h3 class="mb-3 text-[13px] font-semibold text-foreground">时间轴</h3>
        <EmptyState
          v-if="grouped.length === 0"
          icon="clock"
          title="还没有阅读记录"
          desc="开始阅读后，这里会按日汇总你的阅读、批注与成就。"
        />
        <div v-else class="space-y-5">
          <div v-for="day in grouped" :key="day.date">
            <div class="mb-2 text-[12px] font-medium text-muted-foreground">{{ day.date }}</div>
            <div class="space-y-2">
              <div v-for="(e, i) in day.items" :key="i" class="flex items-start gap-2.5 rounded-md px-1.5 py-1 transition-colors hover:bg-muted/50">
                <span class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
                  <Icon :name="eventIcon(e)" class="h-3.5 w-3.5" />
                </span>
                <div class="min-w-0 flex-1">
                  <div class="text-[12.5px] leading-relaxed text-foreground">{{ eventText(e) }}</div>
                </div>
                <span class="shrink-0 font-mono text-[11px] text-muted-foreground">{{ hhmm(e.ts) }}</span>
              </div>
            </div>
          </div>
        </div>
        <div
          v-if="timelineTotal > shownCount"
          class="mt-4 flex items-center justify-between border-t border-border pt-3 text-[11.5px] text-muted-foreground"
        >
          <span>已显示最近 {{ shownCount }} 条 · 共 {{ timelineTotal }} 条</span>
          <Button
            variant="secondary"
            size="sm"
            :disabled="activity.limit >= TIMELINE_MAX"
            @click="loadMore"
          >
            加载更多
          </Button>
        </div>
      </Card>
    </template>

    <EmptyState v-else icon="clock" title="阅读活动加载失败" desc="请稍后重试，或检查后端日志。">
      <template #action>
        <Button variant="secondary" size="sm" @click="activity.load(true, yearOf(range))">重试</Button>
      </template>
    </EmptyState>
  </div>
</template>
