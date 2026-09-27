<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import StatTile from '@/components/ui/StatTile.vue'
import { api, type BookReadingStats, type ReadingAttempt, type ReadingSessionRow } from '@/lib/api'
import { fmtDuration, fmtMinutes } from '@/lib/format'
import { paceText } from '@/lib/readingPace'
import { useUiStore } from '@/stores/ui'

/**
 * 「阅读日志」标签：**这本书**的阅读行为（第 63 期 3/6）。
 *
 * 与「我的记录」标签的分工 —— 两个不是重复入口，主语不同：
 * - 我的记录 = **我的**状态与评价（在读 / 读完、起止日期、评分、书评）—— 那里是**编辑面**；
 * - 阅读日志 = **这本书**读起来是什么样（多久 / 几次 / 读到哪里 / 哪几天）—— 这里是**只读面**。
 *
 * 与左侧栏 `/log`（全站阅读记录）也不重叠：那个回答「我最近读了什么」，这个回答
 * 「这本书我读得怎么样」。⚠️ 这条推翻了第 30 期「按书日志不在详情页（避免与 /log 页
 * 重复入口）」的旧决定 —— 复核记录见 `docs/bookorbit-capability-gap.md` 的那一行。
 *
 * **每块都自己判有没有数据**，不设一个总的「有没有读过」闸门：一本标记过「在读」但从没
 * 在网页上打开过的书（纸质书 / 别的设备读的）没有会话，却有轮次 —— 拿会话去闸轮次，
 * 那块就凭空消失了。
 */
const props = defineProps<{
  bookId: string
  /** 标签页当前是否可见。**数据与图表都等到第一次打开才拉**（见下） */
  active: boolean
  /** 页数与来源（算阅读速度用，判据在 `lib/readingPace.ts`） */
  pages?: number
  pagesSource?: string
}>()

const emit = defineEmits<{ changed: [] }>()

const ui = useUiStore()

const stats = ref<BookReadingStats | null>(null)
/** 初值 true：「还没拉到」与「拉到了但确实没记录」必须分开，否则首帧会闪一下空态 */
const loading = ref(true)
const failed = ref(false)

const attempts = ref<ReadingAttempt[]>([])
const attemptsLoaded = ref(false)

/**
 * 图表**单独**异步加载：它是全站第二个引 ECharts 的地方（第一个是统计页，走路由级
 * 懒加载）。若在这里静态 import，那个 800 kB 量级的图表库会跟着详情页进主包 ——
 * 详情页是高频入口，那个代价不能付。
 *
 * 光拆成 async 组件还不够：`v-if` 若恒真，组件一挂载就会去 download。所以下面
 * 还要求 `chartReady` —— **用户真的点开过这个标签页**才 render。
 */
const ProgressOverTimeChart = defineAsyncComponent(
  () => import('@/components/book/detail/ProgressOverTimeChart.vue'),
)
/** 点开过就一直是 true（单调，不随换书复位）：切走再切回来不重新下载那个 chunk */
const chartReady = ref(false)

/**
 * **每次打开这个标签页都重拉一次**。不缓存：这本是唯一一个「不点开就不请求」的接口
 * （其余五个标签的数据首屏都要用），代价是毫秒级的一次查询，换来的是「刚读完回来
 * 看到的就是刚读完的时长」—— 换成缓存的话，最常见的动作（进阅读器读一会儿再回详情页）
 * 看到的会是打开页面那一刻的旧数。
 */
watch(
  () => props.active,
  (v) => {
    if (!v) return
    chartReady.value = true
    void load()
  },
  { immediate: true },
)

/** 同一条路由记录内换书（`/book/A` → `/book/B`）：重拉这一本的 */
watch(
  () => props.bookId,
  () => {
    if (props.active) void load()
  },
)

async function load(): Promise<void> {
  loading.value = true
  failed.value = false
  stats.value = null
  attempts.value = []
  attemptsLoaded.value = false
  // 两块数据互不依赖，**并行**拉：串行的话轮次列表会比统计晚一个来回才出现
  const attemptsP = loadAttempts()
  try {
    stats.value = await api.bookReadingStats(props.bookId)
  } catch {
    // 「加载失败」与「还没有阅读记录」必须分开：后者是空态，前者要能重试
    failed.value = true
  }
  loading.value = false
  await attemptsP
}

const reading = computed(() => stats.value?.reading ?? null)
const sessions = computed(() => stats.value?.sessions ?? [])
const days = computed(() => stats.value?.days ?? [])
const records = computed(() => stats.value?.records ?? null)

/**
 * 阅读速度：判据在 `lib/readingPace.ts`（与全站 `/log` 页共用一份）。
 * `null` = 这本书的页数不可信（PDF / 有声书），那一格**不渲染** —— 不摆「—」占位，
 * 更不摆「0 页/小时」。
 *
 * 拆成「数值 + 来源」两段是因为 StatTile 的 `hint` 要单独给来源：整串塞进 value
 * 会被 `truncate` 截掉那个括号 —— 而**来源恰恰是这个数字可信度的全部**，
 * 截掉之后「60 页/小时」看起来像实测值。
 */
const pace = computed(() => {
  if (!reading.value) return null
  const s = paceText({
    seconds: reading.value.seconds,
    pages: props.pages,
    pages_source: props.pagesSource,
  })
  if (!s) return null
  const i = s.indexOf('（')
  return i < 0 ? { value: s, hint: '' } : { value: s.slice(0, i), hint: s.slice(i + 1, -1) }
})

// ---------------- 阅读尝试 / 重读 ----------------
// 第 43 期起轮次由后端 `db.set_status` 自动维护（标记「在读 / 已读完」时开轮 / 收尾）。
// 第 63 期 3/6 从「我的记录」搬到**这里**：它记的是「读的行为」，不是「我的评价」。
// 两个用户显式出口照原样保留：手动开新一轮、从历史补录。

async function loadAttempts(): Promise<void> {
  try {
    attempts.value = (await api.readingAttempts(props.bookId)).items
  } catch {
    attempts.value = []
  }
  // `attemptsLoaded` **要等请求落地才置位**：提前置位会让空态文案
  // 「还没有轮次记录」先闪一下，再被真的列表顶掉 —— 那是在说一句**还没核实过**的话
  // （与 `loading` 初值为 `true` 是同一条纪律，见上）
  attemptsLoaded.value = true
}

async function startReRead(): Promise<void> {
  try {
    await api.startReadingAttempt(props.bookId)
    await loadAttempts()
    ui.toast('已开始新的一轮')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
}

async function finishAttempt(): Promise<void> {
  try {
    await api.finishReadingAttempt(props.bookId)
    await loadAttempts()
    ui.toast('已标记这一轮读完')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
}

/** 补录是**全站**操作（后端一次扫所有书），不是只补这一本 —— 文案别写成「补录这本」 */
async function backfillAttempts(): Promise<void> {
  try {
    const r = await api.backfillReadingAttempts()
    await loadAttempts()
    ui.toast(r.created ? `已从历史补录 ${r.created} 本` : '没有需要补录的书')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '补录失败')
  }
}

// ---------------- 展示 ----------------

const SOURCE_LABELS: Record<string, string> = {
  web: '网页阅读器',
  audio: '有声书',
  manual: '手动补录',
}

/** 会话来源徽章；**空串什么都不显示** —— 改造前的存量行分不出来源，不猜（见 db.SESSION_SOURCES） */
function sourceLabel(s: string): string {
  return SOURCE_LABELS[s] ?? ''
}

function dayTime(sec: number): string {
  const d = new Date(sec * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/**
 * 本地日期 `YYYY-MM-DD`。
 *
 * ⚠️ **不用 `toISOString().slice(0, 10)`**：那是 **UTC** 日期，在东八区会把本地
 * 00:00–08:00 之间的时间戳算成前一天 —— 而「起于哪天」正是靠它。服务端给的日期串
 * （`records.*.date`）已经是本地日，两边口径必须一致。
 */
function dayOnly(sec: number): string {
  const d = new Date(sec * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * `CHANGE` 列。`null` → 「—」：第 63 期之前的会话没有进度快照，**补不回来**，
 * 显示 0% 会被读成「这一段没往前走」。
 */
function fmtChange(v: number | null): string {
  if (v === null) return '—'
  const n = Math.round(v * 10) / 10
  return `${n > 0 ? '+' : ''}${n}%`
}

/** 位置列：当天这一段的终点；不知道就是「—」 */
function fmtWhere(s: ReadingSessionRow): string {
  if (s.end_percent === null) return '—'
  const from = s.start_percent === null ? '' : `${s.start_percent.toFixed(0)}% → `
  // 多轨有声书带上当前轨，否则一个书名下的几十段会话分不出是在听哪一轨
  return `${from}${s.end_percent.toFixed(0)}%${s.file_rel ? ` · ${s.file_rel}` : ''}`
}

function shortDate(date: string): string {
  return date.slice(5)
}
</script>

<template>
  <div>
    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <Card v-else-if="failed" padding="none">
      <div class="flex flex-col items-center gap-2 px-4 py-12 text-center">
        <Icon name="alert" class="size-6 text-muted-foreground" />
        <p class="text-[13px] text-foreground">阅读记录加载失败</p>
        <p class="text-[11.5px] text-muted-foreground">这本书的阅读时长与进度快照没能取回来，可以重试。</p>
        <Button size="sm" class="mt-1" @click="load">重试</Button>
      </div>
    </Card>

    <template v-else>
      <!-- READING：这本书的阅读面（只读）。没读过就是一整块空态，不摆六个 0 -->
      <Card v-if="!reading" padding="none">
        <div class="flex flex-col items-center gap-2 px-4 py-12 text-center">
          <Icon name="clock" class="size-6 text-muted-foreground" />
          <p class="text-[13px] text-foreground">还没有阅读记录</p>
          <p class="max-w-[42ch] text-[11.5px] leading-relaxed text-muted-foreground">
            从阅读器里打开这本书，每次连续阅读都会记一段（含读了多久、读到哪）。
            有声书、PDF、漫画同样计时。
          </p>
        </div>
      </Card>

      <Card v-else padding="none">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">阅读统计</h3>
          <p class="mt-1 text-[11px] text-muted-foreground">
            一次连续阅读记一段（切走超过半小时算下一段）；时间来自网页阅读器与播放器，不含其他设备。
          </p>
        </div>
        <div class="grid grid-cols-2 gap-2 px-4 py-3 sm:grid-cols-3 lg:grid-cols-6">
          <StatTile label="累计时长" :value="fmtDuration(reading.seconds)" />
          <StatTile label="会话数" :value="String(reading.sessions)" hint="一次连续阅读 = 一段" />
          <StatTile label="平均单次" :value="fmtDuration(reading.avg_seconds)" />
          <StatTile
            label="活跃天数"
            :value="`${reading.active_days} 天`"
            :hint="`起于 ${dayOnly(reading.first_started)}`"
          />
          <!-- 页数不可信时这一格不渲染（pace 为 null），不摆「—」占位 -->
          <StatTile v-if="pace" label="阅读速度" :value="pace.value" :hint="pace.hint" />
          <StatTile
            label="最近阅读"
            :value="dayTime(reading.last_ended).slice(0, 5)"
            :hint="dayTime(reading.last_ended).slice(6)"
          />
        </div>
      </Card>

      <!-- PROGRESS OVER TIME：懒加载，见文件头 -->
      <div v-if="chartReady && days.length" class="mt-3">
        <ProgressOverTimeChart :days="days" />
      </div>

      <!-- SESSIONS：逐条流水（新 → 旧）。最多 200 条由服务端封顶 -->
      <Card v-if="sessions.length" padding="none" class="mt-3">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">阅读会话</h3>
          <p class="mt-1 text-[11px] text-muted-foreground">
            共 {{ reading?.sessions ?? sessions.length }} 段<template v-if="sessions.length < (reading?.sessions ?? 0)">
              ，这里列出最近 {{ sessions.length }} 段</template>。
            「变化」是这一段读过的百分比 —— 改造前的记录没有进度快照，显示「—」。
          </p>
        </div>
        <div class="max-h-[420px] overflow-auto">
          <!-- 表头吸顶：列表能滚到 420px，滚动时列名必须一直看得见（`bg-muted` 不透明，
               半透明的话行会从表头下面透出来） -->
          <div
            class="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-muted px-4 py-1.5 text-[10.5px] text-muted-foreground"
          >
            <span class="w-[86px] shrink-0">开始</span>
            <span class="w-[72px] shrink-0">时长</span>
            <span class="w-[64px] shrink-0">变化</span>
            <span class="min-w-0 flex-1">位置</span>
            <span class="shrink-0">来源</span>
          </div>
          <div
            v-for="s in sessions"
            :key="s.id"
            data-test="session-row"
            class="flex items-center gap-3 border-b border-border px-4 py-1.5 text-[12px] last:border-b-0"
          >
            <span class="w-[86px] shrink-0 tabular-nums text-muted-foreground">{{ dayTime(s.started_at) }}</span>
            <span class="w-[72px] shrink-0 tabular-nums text-foreground">{{ fmtDuration(s.seconds) }}</span>
            <span
              data-test="session-change"
              class="w-[64px] shrink-0 tabular-nums"
              :class="s.change === null ? 'text-muted-foreground/60' : 'text-foreground'"
            >{{ fmtChange(s.change) }}</span>
            <span class="min-w-0 flex-1 truncate text-muted-foreground" :title="fmtWhere(s)">{{ fmtWhere(s) }}</span>
            <span class="shrink-0 text-[11px] text-muted-foreground">{{ sourceLabel(s.source) }}</span>
          </div>
        </div>
      </Card>

      <!-- RECORDS：四个「这本书之最」。每个都可能没有（没有那个结论就不渲染那一格） -->
      <Card v-if="records" padding="none" class="mt-3">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">阅读之最</h3>
          <p class="mt-1 text-[11px] text-muted-foreground">只算这本书，时间按本机时区归日。</p>
        </div>
        <div class="grid grid-cols-2 gap-2 px-4 py-3 lg:grid-cols-4">
          <StatTile
            label="最长的一次"
            :value="fmtDuration(records.longest_session.seconds)"
            :hint="records.longest_session.date"
          />
          <StatTile
            label="读得最多的一天"
            :value="fmtDuration(records.best_day.seconds)"
            :hint="records.best_day.date"
          />
          <StatTile
            label="会话最多的一天"
            :value="`${records.busiest_day.sessions} 次`"
            :hint="records.busiest_day.date"
          />
          <!-- 连续天数可能没有（只有一天记录时后端给 null）⇒ 那一格不渲染 -->
          <StatTile
            v-if="records.longest_streak"
            label="最长连续"
            :value="`${records.longest_streak.days} 天`"
            :hint="`${shortDate(records.longest_streak.start)} → ${shortDate(records.longest_streak.end)}`"
          />
        </div>
      </Card>

      <!-- ATTEMPTS：重读轮次。**与上面几块独立** —— 状态切换就会开轮，
          一本从没在网页上打开过的书也可能有轮次，所以它不挂在 `reading` 上 -->
      <Card padding="none" class="mt-3">
        <div class="flex items-start gap-3 border-b border-border px-4 py-3">
          <div class="min-w-0 flex-1">
            <h3 class="text-[13px] font-semibold text-foreground">阅读尝试 / 重读</h3>
            <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
              一轮 = 「开始读 → 读完」；读完后再开始就是新一轮，这里记着读过几遍与每轮起止时间。
              标记「在读 / 已读完」会自动维护轮次，也可以手动开一轮。
            </p>
          </div>
          <Button size="sm" variant="ghost" @click="startReRead">再来一遍</Button>
        </div>
        <div v-if="attempts.length" class="divide-y divide-border">
          <div
            v-for="a in attempts"
            :key="a.id"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[12.5px]"
          >
            <span class="font-mono text-[11px] tabular-nums text-muted-foreground">第 {{ a.round }} 轮</span>
            <span class="text-foreground">{{ dayTime(a.started_at).slice(0, 5) }}</span>
            <span class="text-muted-foreground">→</span>
            <span :class="a.finished_at ? 'text-foreground' : 'text-muted-foreground'">
              {{ a.finished_at ? dayTime(a.finished_at).slice(0, 5) : '进行中' }}
            </span>
            <Button v-if="!a.finished_at" size="sm" variant="ghost" class="ml-auto" @click="finishAttempt">
              标记读完
            </Button>
            <span
              v-else
              class="ml-auto rounded bg-muted px-1.5 py-0.5 text-[10.5px] text-muted-foreground"
            >已完成</span>
          </div>
        </div>
        <div v-else-if="attemptsLoaded" class="px-4 py-3 text-[11.5px] leading-relaxed text-muted-foreground">
          还没有轮次记录。标记「在读 / 已读完」会自动记一轮，也可以点「再来一遍」手动开一轮。
          <button
            type="button"
            class="ml-1 cursor-pointer underline underline-offset-2 hover:text-foreground"
            @click="backfillAttempts"
          >
            从历史补录
          </button>
        </div>
      </Card>
    </template>
  </div>
</template>
