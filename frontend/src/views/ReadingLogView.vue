<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, apiErrorMessage, type ReadingLogBook, type ReadingLogDay, type ReadingLogSession } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * Reading Log（阅读记录）：`reading_sessions` 表的展示层。
 *
 * 数据在阅读器每次退出时落库，这里只做三种聚合，不做任何写入：
 *   · 按天 —— 每天读了多久、分几次、读了哪些书（窗口内）；
 *   · 按书 —— 累计时长 / 会话数 / 最近一次，看得出行数据被孤儿清理清掉与否；
 *   · 最近 —— 逐条会话明细。
 */
const router = useRouter()
const library = useLibraryStore()
const ui = useUiStore()
const loading = ref(true)
const days = ref(60)
const items = ref<ReadingLogDay[]>([])
const byBook = ref<ReadingLogBook[]>([])
const recent = ref<ReadingLogSession[]>([])
/** 加载失败：与「还没有阅读记录」分开渲染，别把错误当空态。 */
const failed = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    const r = await api.readingLog(days.value)
    items.value = r.items
    byBook.value = r.by_book
    recent.value = r.recent
    failed.value = false
  } catch (e) {
    failed.value = true
    ui.toast(apiErrorMessage(e, '阅读记录加载失败'))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  library.loadBooks().catch(() => {})
})

function setDays(d: number): void {
  days.value = d
  load()
}

// ---- 手工补录（上游 Add a session by hand）：读了纸质书 / 没开阅读器的时间 ----
const formOpen = ref(false)
const busy = ref(false)
// 开始时间默认「现在 − 时长」：补录的常见语义是「刚读完一段」，
// 会话结束于现在。若默认开始 = 现在，加上时长后结束落在未来，会被后端拒绝。
const form = ref({
  book_id: '',
  minutes: 30,
  date: new Date().toISOString().slice(0, 10),
  start: '',
})

function openForm(): void {
  formOpen.value = !formOpen.value
  if (formOpen.value) {
    form.value.start = new Date(Date.now() - form.value.minutes * 60000).toTimeString().slice(0, 5)
  }
}

async function submitSession(): Promise<void> {
  if (!form.value.book_id) {
    ui.toast('先选一本书')
    return
  }
  busy.value = true
  try {
    const r = await api.addReadingSession({ ...form.value, minutes: Number(form.value.minutes) })
    ui.toast(`已补录：结束于 ${r.session.date}`)
    formOpen.value = false
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '补录失败')
  } finally {
    busy.value = false
  }
}

const INPUT_CLS =
  'h-8 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card'

function human(sec: number): string {
  if (sec <= 0) return '—'
  const m = Math.round(sec / 60)
  if (m < 60) return `${m} 分钟`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

/** 平均单次时长（秒 → 「23 分钟/次」） */
function avgText(sec: number): string {
  if (!sec || sec <= 0) return '—'
  const m = Math.round(sec / 60)
  if (m < 60) return `${m} 分钟/次`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分/次`
}

/**
 * 阅读速度（页/小时）：有可靠页数才显示，否则返回空（不造假）。
 * 可靠 = pages_source 为 'estimate'（EPUB 估算）或 'archive'（漫画真实值）且 pages>0。
 */
function paceText(b: ReadingLogBook): string {
  if (!b.pages || b.pages <= 0) return ''
  if (b.pages_source !== 'estimate' && b.pages_source !== 'archive') return ''
  const hours = (b.seconds || 0) / 3600
  if (hours <= 0) return ''
  const pph = b.pages / hours
  const src = b.pages_source === 'archive' ? '真实页数' : '估算页数'
  return `${pph.toFixed(0)} 页/小时（${src}）`
}

const peak = computed(() => Math.max(1, ...items.value.map((d) => d.seconds)))
function barHeight(sec: number): string {
  return `${Math.max(4, (sec / peak.value) * 100).toFixed(1)}%`
}
function dayLabel(d: ReadingLogDay): string {
  const today = new Date().toISOString().slice(0, 10)
  if (d.date === today) return '今天'
  return d.date.slice(5)
}
</script>

<template>
  <div class="mx-auto w-full max-w-6xl px-5 py-6">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div>
        <h1 class="text-[17px] font-semibold text-foreground">阅读记录</h1>
        <p class="mt-0.5 text-[12px] text-muted-foreground">
          阅读器每次退出都会记一条会话（时长、起止）。这里只做聚合展示，不产生任何写入。
        </p>
      </div>
      <div class="ml-auto flex gap-1.5">
        <Button v-for="d in [30, 60, 90]" :key="d" size="sm" :variant="days === d ? 'primary' : 'ghost'" @click="setDays(d)">
          {{ d }} 天
        </Button>
        <Button size="sm" variant="primary" class="ml-2" @click="openForm">
          补录
        </Button>
      </div>
    </div>

    <Card v-if="formOpen" padding="none" class="mb-3">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">手工补录一次阅读</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          读纸质书、或在没开阅读器的地方看了一会儿 —— 补上这段时间，统计与柱状图才会完整。
        </p>
      </div>
      <div class="flex flex-wrap items-end gap-3 px-4 py-3">
        <label class="flex min-w-52 flex-1 flex-col gap-1">
          <span class="text-[11.5px] text-muted-foreground">书</span>
          <select v-model="form.book_id" :class="INPUT_CLS">
            <option value="" disabled>选择一本书…</option>
            <option v-for="b in library.books" :key="b.id" :value="b.id">
              {{ b.title }}{{ b.author ? ` · ${b.author}` : '' }}
            </option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11.5px] text-muted-foreground">日期</span>
          <input v-model="form.date" type="date" :class="INPUT_CLS">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11.5px] text-muted-foreground">开始</span>
          <input v-model="form.start" type="time" :class="INPUT_CLS">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11.5px] text-muted-foreground">时长（分钟）</span>
          <input v-model="form.minutes" type="number" min="1" max="1440" class="w-24 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card">
        </label>
        <Button size="sm" variant="primary" :disabled="busy" @click="submitSession">
          {{ busy ? '保存中…' : '记下这段' }}
        </Button>
      </div>
    </Card>

    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <EmptyState
      v-else-if="failed"
      icon="alert"
      title="阅读记录加载失败"
      desc="请稍后重试，或检查后端日志。"
    >
      <template #action>
        <Button size="sm" variant="secondary" @click="load">重试</Button>
      </template>
    </EmptyState>

    <EmptyState
      v-else-if="!items.length"
      icon="clock"
      title="还没有阅读记录"
      desc="打开任意一本 EPUB 阅读一会儿，退出后这里就会出现按天与按书的统计。"
    />

    <template v-else>
      <div class="mb-3 flex flex-wrap gap-2">
        <span class="rounded-md bg-muted px-2.5 py-1 text-[12px] text-muted-foreground">
          窗口内共 <b class="text-foreground">{{ human(items.reduce((s, d) => s + d.seconds, 0)) }}</b>
        </span>
        <span class="rounded-md bg-muted px-2.5 py-1 text-[12px] text-muted-foreground">
          {{ items.reduce((s, d) => s + d.sessions, 0) }} 次会话 · {{ items.length }} 个活跃天
        </span>
        <span class="rounded-md bg-muted px-2.5 py-1 text-[12px] text-muted-foreground">
          读过 {{ byBook.length }} 本书
        </span>
      </div>

      <!-- 按天柱状图：悬停显示当天明细 -->
      <Card padding="none" class="mb-3">
        <div class="border-b border-border px-4 py-3 text-[13px] font-semibold text-foreground">按天</div>
        <div class="flex h-36 items-end gap-[3px] px-4 py-3">
          <div
            v-for="d in items"
            :key="d.date"
            class="group relative flex-1 cursor-default rounded-t bg-primary/70 transition-colors hover:bg-primary"
            :style="{ height: barHeight(d.seconds) }"
            :title="`${d.date} · ${human(d.seconds)} · ${d.sessions} 次`"
          >
            <div
              class="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden w-44 -translate-x-1/2 rounded-md border border-border bg-card p-2 text-[11px] shadow-lg group-hover:block"
            >
              <p class="font-semibold text-foreground">{{ dayLabel(d) }} · {{ human(d.seconds) }}</p>
              <p v-for="b in d.books" :key="b.id" class="mt-0.5 truncate text-muted-foreground">
                {{ b.title }} · {{ human(b.seconds) }}
              </p>
            </div>
          </div>
        </div>
      </Card>

      <div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <!-- 按书聚合 -->
        <Card padding="none">
          <div class="border-b border-border px-4 py-3 text-[13px] font-semibold text-foreground">按书</div>
          <div
            v-for="b in byBook"
            :key="b.id"
            class="flex cursor-pointer items-center gap-3 border-b border-border px-4 py-2.5 transition-colors last:border-b-0 hover:bg-muted"
            @click="router.push(`/book/${b.id}`)"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-[12.5px] text-foreground">{{ b.title }}</p>
              <p class="truncate text-[11px] text-muted-foreground">
                {{ b.author || '未知作者' }} · {{ b.sessions }} 次 · 平均 {{ avgText(b.avg_seconds) }}
              </p>
              <p class="truncate text-[11px] text-muted-foreground">
                最近 {{ new Date(b.last_ended * 1000).toLocaleDateString() }}<template v-if="paceText(b)"> · {{ paceText(b) }}</template>
              </p>
            </div>
            <span class="shrink-0 text-[12px] tabular-nums text-muted-foreground">{{ human(b.seconds) }}</span>
          </div>
        </Card>

        <!-- 最近会话 -->
        <Card padding="none">
          <div class="border-b border-border px-4 py-3 text-[13px] font-semibold text-foreground">最近会话</div>
          <div
            v-for="(s, i) in recent.slice(0, 20)"
            :key="i"
            class="flex items-center gap-3 border-b border-border px-4 py-2 last:border-b-0"
          >
            <div class="min-w-0 flex-1">
              <p class="truncate text-[12.5px] text-foreground">{{ s.title }}</p>
              <p class="text-[11px] tabular-nums text-muted-foreground">{{ s.date }}</p>
            </div>
            <span class="shrink-0 text-[12px] tabular-nums text-muted-foreground">{{ human(s.seconds) }}</span>
          </div>
        </Card>
      </div>
    </template>
  </div>
</template>
