<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api } from '@/lib/api'
import {
  COMIC_BGS,
  COMIC_DIRECTIONS,
  COMIC_FITS,
  COMIC_MODES,
  COMIC_RANGES,
  COMIC_PAGE_VIEWS,
  comicBg,
  readComicPrefs,
  saveComicPrefs,
  type ComicPrefs,
} from '@/lib/comicPrefs'

/**
 * 漫画阅读器（CBZ）。
 *
 * 页图按需取：`/api/books/{id}/comic/{index}`，**不一次拉整本**（一话可能几十 MB）。
 * ⚠️ 该接口必须允许 `?token=`（见 server._MEDIA_TOKEN_PATHS）——`<img src>` 是浏览器
 * 原生请求，带不了 Authorization 头，与封面/字体同一约束。
 *
 * 只支持 CBZ；CBR（RAR）需要额外解压依赖，后端会直接拒绝。
 */
const props = defineProps<{ bookId: string; title: string }>()
const router = useRouter()

const prefs = ref<ComicPrefs>(readComicPrefs())
watch(prefs, (v) => saveComicPrefs(v), { deep: true })

const boxRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref('')
const total = ref(0)
const page = ref(1)

const bgStyle = computed(() => ({ background: comicBg(prefs.value) }))
const double = computed(() => prefs.value.pageView === 'double')
const rtl = computed(() => prefs.value.direction === 'rtl')

/** 页图 URL（index 从 0 起）。带 token 的拼法集中在 api.comicPageUrl（那里解释了为什么需要） */
function pageUrl(index: number): string {
  return api.comicPageUrl(props.bookId, index)
}

/** 翻页模式下当前要显示的页（1-based）；双页时含下一页，并按阅读方向排列 */
const shown = computed(() => {
  if (!total.value) return [] as number[]
  if (!double.value) return [page.value]
  // 双页从奇数页开始更符合装订：左=奇数、右=偶数（ltr）；rtl 时左右互换由 CSS 处理
  const first = page.value % 2 === 0 ? page.value - 1 : page.value
  const a = Math.max(1, first)
  const b = a + 1
  const arr = [a, b].filter((n) => n <= total.value)
  return rtl.value ? [...arr].reverse() : arr
})

/** 图片适配：page = 整页可见，width/height 分别锁一边，actual = 原始像素 */
const imgStyle = computed(() => {
  const p = prefs.value
  if (p.fit === 'width') return { width: '100%', height: 'auto' }
  if (p.fit === 'height') return { height: '100%', width: 'auto' }
  if (p.fit === 'actual') return {}
  return { maxWidth: '100%', maxHeight: '100%', width: 'auto', height: 'auto' }
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const r = await api.comicPages(props.bookId)
    total.value = r.total
    if (!r.total) {
      error.value = '这本漫画里没有可显示的图片'
      loading.value = false
      return
    }
    try {
      const p = await api.getProgress(props.bookId)
      page.value = Math.min(r.total, Math.max(1, (p.locator || 0) + 1))
    } catch {
      /* 无进度则从第 1 页开始 */
    }
    loading.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : '漫画打开失败'
    loading.value = false
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
function scheduleSave(): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void save(), 600)
}

async function save(): Promise<void> {
  if (!total.value) return
  try {
    await api.setProgress(props.bookId, page.value - 1, (page.value / total.value) * 100)
  } catch {
    /* 静默 */
  }
}

function go(n: number): void {
  const step = double.value ? 2 : 1
  const next = Math.min(Math.max(1, n), total.value)
  if (next === page.value) return
  page.value = next
  void save()
  if (prefs.value.mode === 'infinite') {
    boxRef.value?.querySelector(`[data-p="${next}"]`)?.scrollIntoView({ block: 'start' })
  }
  void step
}

function next(): void {
  go(page.value + (double.value ? 2 : 1))
}
function prev(): void {
  go(page.value - (double.value ? 2 : 1))
}

/** 点击左右区域翻页；rtl（日漫）时语义反转 —— 右到左读就是「点右边看下一页」反过来的直觉 */
function onBoxClick(e: MouseEvent): void {
  const el = boxRef.value
  if (!el || prefs.value.mode !== 'paginated') return
  const r = el.getBoundingClientRect()
  const x = (e.clientX - r.left) / r.width
  const forwardLeft = rtl.value // 右到左阅读：左侧 = 下一页
  if (x < 0.33) (forwardLeft ? next : prev)()
  else if (x > 0.67) (forwardLeft ? prev : next)()
}

function onKeydown(e: KeyboardEvent): void {
  const step = double.value ? 2 : 1
  if (e.key === 'ArrowRight' || e.key === 'PageDown') go(page.value + (rtl.value ? -step : step))
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(page.value + (rtl.value ? step : -step))
}

let io: IntersectionObserver | null = null

/** 连续模式下按滚动位置更新当前页（用于进度与页码显示） */
function onScroll(): void {
  const el = boxRef.value
  if (!el || prefs.value.mode !== 'infinite') return
  const r = el.getBoundingClientRect()
  const line = r.top + 8
  let cur = 1
  for (const node of el.querySelectorAll('[data-p]')) {
    if ((node as HTMLElement).getBoundingClientRect().top <= line) {
      cur = Math.max(cur, Number((node as HTMLElement).dataset.p || 1))
    }
  }
  if (cur !== page.value) {
    page.value = cur
    scheduleSave()
  }
}

onMounted(async () => {
  await load()
  window.addEventListener('keydown', onKeydown)
  if (typeof IntersectionObserver === 'function') {
    io = new IntersectionObserver(() => {
      /* 连续模式的重活交给浏览器原生 loading="lazy"；这里只用于保持引用 */
    })
  }
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  void save()
  window.removeEventListener('keydown', onKeydown)
  io?.disconnect()
})

// 双页/方向变化时页码要落到「双页起点」，否则会停在第 2、4 页这类看着别扭的位置
watch([double, rtl], () => {
  if (double.value && page.value % 2 === 0) page.value = Math.max(1, page.value - 1)
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 工具栏 -->
    <div class="flex flex-wrap items-center gap-2 border-b border-border pb-2">
      <Button size="sm" variant="ghost" title="返回详情" @click="router.push(`/book/${props.bookId}`)">
        <Icon name="arrowLeft" class="h-4 w-4" />
      </Button>
      <div class="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">{{ props.title }}</div>

      <Button size="sm" variant="ghost" title="上一页" :disabled="page <= 1" @click="prev">
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
      </Button>
      <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ page }} / {{ total }}</span>
      <Button size="sm" variant="ghost" title="下一页" :disabled="page >= total" @click="next">
        <Icon name="arrowRight" class="h-3.5 w-3.5" />
      </Button>

      <span class="mx-1 h-4 w-px bg-border" />
      <select
        v-model="prefs.mode"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="阅读模式"
      >
        <option v-for="m in COMIC_MODES" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <select
        v-model="prefs.pageView"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="页视图"
      >
        <option v-for="v in COMIC_PAGE_VIEWS" :key="v.key" :value="v.key">{{ v.label }}</option>
      </select>
      <select
        v-model="prefs.fit"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="适配方式"
      >
        <option v-for="f in COMIC_FITS" :key="f.key" :value="f.key">{{ f.label }}</option>
      </select>
      <select
        v-model="prefs.direction"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="阅读方向"
      >
        <option v-for="d in COMIC_DIRECTIONS" :key="d.key" :value="d.key">{{ d.label }}</option>
      </select>
      <select
        v-model="prefs.bg"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="背景色"
      >
        <option v-for="b in COMIC_BGS" :key="b.key" :value="b.key">{{ b.label }}</option>
      </select>
      <span class="text-[11px] text-muted-foreground">间距</span>
      <input
        v-model.number="prefs.gap"
        type="range"
        class="w-20"
        :min="COMIC_RANGES.gap.min"
        :max="COMIC_RANGES.gap.max"
        :step="COMIC_RANGES.gap.step"
        aria-label="页间距"
      >
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>
    <div v-else-if="error" class="py-20 text-center text-[13px] text-destructive">{{ error }}</div>

    <!-- 页图区 -->
    <div
      v-show="!loading && !error"
      ref="boxRef"
      class="min-h-0 flex-1 overflow-auto"
      :style="bgStyle"
      @scroll="onScroll"
      @click="onBoxClick"
    >
      <!-- 翻页：只挂当前页（双页时两页并排） -->
      <div
        v-if="prefs.mode === 'paginated'"
        class="flex h-full items-center justify-center"
        :style="{ gap: `${prefs.gap}px` }"
      >
        <img
          v-for="n in shown"
          :key="n"
          :src="pageUrl(n - 1)"
          :style="imgStyle"
          class="block select-none"
          draggable="false"
          :alt="`第 ${n} 页`"
        >
      </div>

      <!-- 纵向连续：全部页懒加载（原生 loading="lazy"），页间距可调 -->
      <div v-else class="flex flex-col items-center" :style="{ gap: `${prefs.gap}px`, paddingBottom: '1.5rem' }">
        <img
          v-for="n in total"
          :key="n"
          :data-p="n"
          :src="pageUrl(n - 1)"
          :style="imgStyle"
          class="block select-none"
          loading="lazy"
          draggable="false"
          :alt="`第 ${n} 页`"
        >
      </div>
    </div>
  </div>
</template>
