<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type BookReview, type ReadingAttempt, type ReadingStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 「我的记录」标签：阅读状态 + 起止日期 + 评分 + 书评。
 *
 * 口径与后端 db.set_status 的日期规则对应：
 *   · 起止日期由**状态切换自动维护**（进入 reading/finished 记开始、进入 finished 记结束、
 *     回到 unread 全清），这里只提供**手工修正**入口 —— 历史日期没法从进度里推断；
 *   · 有了真实状态字段，「搁置 / 弃读」这类进度表达不了的状态才成为可能。
 */
const props = defineProps<{ bookId: string }>()
const emit = defineEmits<{ changed: [] }>()

const ui = useUiStore()
const loading = ref(true)
const saving = ref(false)
const st = ref<ReadingStatus | null>(null)
const rv = ref<BookReview | null>(null)
/** 阅读尝试（轮次，第 43 期）：一轮 = 开始读 → 读完 */
const attempts = ref<ReadingAttempt[]>([])

const STATUS_OPTIONS = [
  { value: 'unread', label: '未读' },
  { value: 'reading', label: '在读' },
  { value: 'finished', label: '已读完' },
  { value: 'paused', label: '搁置' },
  { value: 'abandoned', label: '弃读' },
] as const

const label = (v: string) => STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v

/** <input type=date> 用 YYYY-MM-DD；0 显示为空 */
function toInput(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toISOString().slice(0, 10)
}
function fromInput(s: string): number {
  if (!s) return 0
  const t = Date.parse(s) / 1000
  return Number.isFinite(t) ? t : 0
}

const started = ref('')
const finished = ref('')
const review = ref('')
const stars = ref(0)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [s, r] = await Promise.all([api.bookStatus(props.bookId), api.bookReview(props.bookId)])
    st.value = s
    rv.value = r
    started.value = toInput(s.started_at)
    finished.value = toInput(s.finished_at)
    review.value = r.review
    stars.value = r.stars
    await loadAttempts()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '记录加载失败')
  }
  loading.value = false
}

onMounted(load)
watch(() => props.bookId, load)

// ---- 阅读尝试 / 重读（第 43 期）----
// 轮次由后端 `db.set_status` 自动维护（标记「在读 / 已读完」时开轮 / 收尾）；
// 这里提供两个**用户显式**的出口：「再来一遍」（手动开新一轮）与「从历史补录」。

async function loadAttempts(): Promise<void> {
  try {
    attempts.value = (await api.readingAttempts(props.bookId)).items
  } catch {
    attempts.value = []
  }
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

async function backfillAttempts(): Promise<void> {
  try {
    const r = await api.backfillReadingAttempts()
    await loadAttempts()
    ui.toast(r.created ? `已从历史补录 ${r.created} 本` : '没有需要补录的书')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '补录失败')
  }
}

const dirtyDates = computed(() => {
  if (!st.value) return false
  return (
    started.value !== toInput(st.value.started_at) ||
    finished.value !== toInput(st.value.finished_at)
  )
})

const dirty = computed(() => {
  if (!rv.value) return false
  return dirtyDates.value || review.value !== rv.value.review || stars.value !== rv.value.stars
})

async function setStatus(status: string): Promise<void> {
  if (!st.value) return
  try {
    // 带上界面上正在编辑的日期：显式日期优先，界面改过的不会被覆盖
    const r = await api.setStatus(props.bookId, {
      status,
      started_at: fromInput(started.value),
      finished_at: fromInput(finished.value),
    })
    st.value = r
    started.value = toInput(r.started_at)
    finished.value = toInput(r.finished_at)
    await loadAttempts()
    ui.toast(`已标记为「${label(status)}」`)
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  }
}

async function save(): Promise<void> {
  if (!st.value || !rv.value) return
  saving.value = true
  try {
    const r = await api.setReview(props.bookId, { stars: stars.value, review: review.value })
    rv.value = r
    if (dirtyDates.value) {
      const s = await api.setStatus(props.bookId, {
        status: st.value.status,
        started_at: fromInput(started.value),
        finished_at: fromInput(finished.value),
      })
      st.value = s
      started.value = toInput(s.started_at)
      finished.value = toInput(s.finished_at)
    }
    ui.toast('已保存')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

const INPUT_CLS =
  'h-8 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card'

// ---------------- 从头开始（第 34 期）----------------
// 「试读了几页想重新来过」原本没有出口。口径（与后端 db.reset_reading_state 一致）：
// 只删**读出来的痕迹**（会话 / 进度 / 状态），批注 / 书签 / 评分 / 收藏 / 元数据都不动，
// 磁盘上的文件更是分毫不碰。不可撤销 ⇒ 先 `window.confirm`（与全站既有确认同一写法）。
const resetting = ref(false)

async function resetReadingState(): Promise<void> {
  const ok = window.confirm(
    '从头开始？会清空这本书的阅读时长、阅读进度、阅读状态与阅读尝试（轮次）。\n\n' +
      '批注、书签、评分与书评都会保留，磁盘上的文件也不会被改动。此操作不可撤销。',
  )
  if (!ok) return
  resetting.value = true
  try {
    const r = await api.resetReadingState(props.bookId)
    ui.toast(`已重置：清掉 ${r.total} 条阅读记录`)
    await load()          // 状态与日期回读（status 变回 unread、日期清空）
    emit('changed')       // 父级刷新进度条 / 阅读记录卡
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '重置失败')
  } finally {
    resetting.value = false
  }
}
</script>

<template>
  <div>
    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="st && rv">
      <Card padding="none" class="mb-3">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">阅读状态</h3>
          <p class="mt-1 text-[11.5px] text-muted-foreground">
            起止日期随状态自动维护（标记「已读完」会记下完成日）；有出入时可在下面手工修正。
          </p>
        </div>
        <div class="flex flex-wrap gap-2 px-4 py-3">
          <button
            v-for="o in STATUS_OPTIONS"
            :key="o.value"
            type="button"
            class="rounded-full border px-3 py-1 text-[12px] transition-colors"
            :class="
              st.status === o.value
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border text-muted-foreground hover:border-ring hover:text-foreground'
            "
            @click="setStatus(o.value)"
          >
            {{ o.label }}
          </button>
        </div>
        <div class="flex flex-wrap items-center gap-4 border-t border-border px-4 py-3">
          <label class="flex items-center gap-2">
            <span class="text-[11.5px] text-muted-foreground">开始于</span>
            <input v-model="started" type="date" :class="INPUT_CLS">
          </label>
          <label class="flex items-center gap-2">
            <span class="text-[11.5px] text-muted-foreground">读完于</span>
            <input v-model="finished" type="date" :class="INPUT_CLS" :disabled="st.status !== 'finished'">
          </label>
          <span v-if="!st.started_at" class="text-[11px] text-muted-foreground">
            还没有开始记录 —— 标记「在读」后会记下今天
          </span>
        </div>
      </Card>

      <Card padding="none">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">我的评分与书评</h3>
        </div>
        <div class="px-4 py-3">
          <div class="flex items-center gap-1.5">
            <button
              v-for="n in 5"
              :key="n"
              type="button"
              class="text-[18px] leading-none transition-transform hover:scale-110"
              :class="n <= stars ? 'text-warning' : 'text-muted-foreground/30'"
              :aria-label="`${n} 星`"
              @click="stars = n"
            >
              ★
            </button>
            <button
              v-if="stars"
              type="button"
              class="ml-2 text-[11px] text-muted-foreground underline-offset-2 hover:underline"
              @click="stars = 0"
            >
              清除
            </button>
            <span v-if="stars" class="ml-1 text-[11.5px] text-muted-foreground">{{ stars }} / 5</span>
          </div>
          <textarea
            v-model="review"
            rows="4"
            placeholder="写点什么……（留空 = 不写书评）"
            class="mt-2.5 w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
          />
        </div>
        <div class="flex items-center gap-3 border-t border-border px-4 py-3">
          <span v-if="dirtyDates" class="text-[11.5px] text-muted-foreground">日期有手工修正，保存后生效</span>
          <Button
            size="sm"
            variant="primary"
            class="ml-auto"
            :disabled="saving || !dirty"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </Button>
        </div>
      </Card>

      <!-- 阅读尝试 / 重读（第 43 期）：一轮 = 「开始读 → 读完」，读完后再开始就是新一轮 -->
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
            <span class="text-foreground">{{ toInput(a.started_at) || '—' }}</span>
            <span class="text-muted-foreground">→</span>
            <span :class="a.finished_at ? 'text-foreground' : 'text-muted-foreground'">
              {{ a.finished_at ? toInput(a.finished_at) : '进行中' }}
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
        <div v-else class="px-4 py-3 text-[11.5px] leading-relaxed text-muted-foreground">
          还没有轮次记录。标记「在读 / 已读完」会自动记一轮，也可以点「再来一遍」手动开一轮。
          <button
            v-if="st && (st.started_at || st.finished_at)"
            type="button"
            class="ml-1 cursor-pointer underline underline-offset-2 hover:text-foreground"
            @click="backfillAttempts"
          >
            从历史补录
          </button>
        </div>
      </Card>

      <!-- 从头开始：只清阅读痕迹，不碰笔记与文件 -->
      <Card padding="none" class="mt-3">
        <div class="border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">从头开始</h3>
          <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
            清空这本书的阅读时长、阅读进度、阅读状态与阅读尝试（轮次），回到还没读过的样子。
            <br>
            批注、书签、评分与书评都会保留；磁盘上的文件不会被改动。此操作不可撤销。
          </p>
        </div>
        <div class="flex items-center gap-3 px-4 py-3">
          <Button size="sm" :disabled="resetting" @click="resetReadingState">
            {{ resetting ? '重置中…' : '重置阅读状态' }}
          </Button>
        </div>
      </Card>
    </template>
  </div>
</template>
