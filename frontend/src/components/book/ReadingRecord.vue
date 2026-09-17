<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type BookReview, type ReadingStatus } from '@/lib/api'
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
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '记录加载失败')
  }
  loading.value = false
}

onMounted(load)
watch(() => props.bookId, load)

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
    </template>
  </div>
</template>
