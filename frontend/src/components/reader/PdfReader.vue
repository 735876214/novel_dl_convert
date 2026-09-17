<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api } from '@/lib/api'
import {
  PDF_FITS,
  PDF_SCROLL_MODES,
  PDF_SPREADS,
  readPdfPrefs,
  savePdfPrefs,
  type PdfPrefs,
} from '@/lib/pdfPrefs'

/**
 * PDF 阅读器。
 *
 * **体积策略（关键）**：pdf.js 用动态 `import()` 懒加载 —— 只有真正打开 PDF 才会
 * 下载那两个 chunk（主包 gzip 117KB + worker gzip 291KB），书架/EPUB 阅读器完全不受影响。
 * worker 用 `?url` 由 Vite 打包成独立文件自托管，不走 CDN（NAS 内网无外网）。
 *
 * 渲染策略：滚动模式按 IntersectionObserver 懒渲染每页 canvas（长文档不会一次性画几百页）；
 * 翻页模式只渲染当前页（双页时含下一页）。缩放/适配变化时清空重画。
 */
const props = defineProps<{ bookId: string; title: string }>()
const router = useRouter()

const prefs = ref<PdfPrefs>(readPdfPrefs())
watch(prefs, (v) => savePdfPrefs(v), { deep: true })

const boxRef = ref<HTMLElement | null>(null)
const loading = ref(true)
const error = ref('')
const total = ref(0)
const page = ref(1)
const boxW = ref(0)
const boxH = ref(0)
/** 第一页的基准尺寸（PDF 单位），用于在没有 canvas 时推算占位高度 */
const base = ref({ w: 612, h: 792 })
const drawn = ref<Set<number>>(new Set())

let pdfDoc: any = null
const canvases = new Map<number, HTMLCanvasElement>()
const slots = new Map<number, HTMLElement>()
const busy = new Set<number>()
let io: IntersectionObserver | null = null
let saveTimer: ReturnType<typeof setTimeout> | null = null

const spreadOn = computed(
  () => prefs.value.spread !== 'none' && (prefs.value.spread !== 'auto' || boxW.value > 900),
)

/** 翻页模式下要显示的页号 */
const shown = computed(() => {
  if (prefs.value.scrollMode !== 'page') return [] as number[]
  if (!spreadOn.value) return [page.value]
  // 奇右 / 偶右决定并排的是哪两页：奇右 → [奇数, 下一页]，偶右 → [上一页, 偶数]
  const start = prefs.value.spread === 'even' ? page.value - (page.value % 2 === 1 ? 1 : 0)
    : page.value - (page.value % 2 === 0 ? 1 : 0)
  return [start, start + 1].filter((p) => p >= 1 && p <= total.value)
})

const scale = computed(() => {
  const pad = 40
  const w = Math.max(200, boxW.value - pad)
  const h = Math.max(200, boxH.value - pad)
  if (prefs.value.fit === 'custom') return prefs.value.zoom
  const perPage = spreadOn.value ? 2 : 1
  const fitW = w / perPage / base.value.w
  const fitH = h / base.value.h
  if (prefs.value.fit === 'page') return Math.min(fitW, fitH)
  if (prefs.value.fit === 'auto') return Math.min(fitW, fitH, 1) // 不放大超过 100%
  return fitW
})

/** 占位高度：用基准尺寸 × 缩放（canvas 定型前先撑住版式，避免滚动条跳动） */
function slotStyle(n: number = 1): Record<string, string> {
  void n
  return { width: `${Math.round(base.value.w * scale.value)}px`, minHeight: `${Math.round(base.value.h * scale.value)}px` }
}

function setCanvas(n: number, el: unknown): void {
  if (el instanceof HTMLCanvasElement) canvases.set(n, el)
  else canvases.delete(n)
}

function setSlot(n: number, el: unknown): void {
  if (!(el instanceof HTMLElement)) {
    slots.delete(n)
    return
  }
  slots.set(n, el)
  io?.observe(el)
}

async function renderPage(n: number): Promise<void> {
  const canvas = canvases.get(n)
  if (!pdfDoc || !canvas || busy.has(n) || drawn.value.has(n)) return
  busy.add(n)
  try {
    const p = await pdfDoc.getPage(n)
    const vp = p.getViewport({ scale: scale.value })
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = Math.floor(vp.width * dpr)
    canvas.height = Math.floor(vp.height * dpr)
    canvas.style.width = `${Math.floor(vp.width)}px`
    canvas.style.height = `${Math.floor(vp.height)}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    await p.render({
      canvasContext: ctx,
      viewport: vp,
      transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
    }).promise
    drawn.value = new Set(drawn.value).add(n)
    const slot = slots.get(n)
    if (slot && n === 1) base.value = { w: vp.width / scale.value || base.value.w, h: vp.height / scale.value || base.value.h }
  } catch {
    /* 单页渲染失败不致命，其余页继续 */
  } finally {
    busy.delete(n)
  }
}

/** 缩放/适配变化后必须重画（canvas 的像素尺寸已变） */
function redraw(): void {
  drawn.value = new Set()
  const targets = prefs.value.scrollMode === 'page' ? shown.value : visibleSlots()
  for (const n of targets) void renderPage(n)
}

/** 滚动模式下「当前在视口里的页」——用于懒渲染与进度 */
function visibleSlots(): number[] {
  const box = boxRef.value
  if (!box) return []
  const out: number[] = []
  for (const [n, el] of slots) {
    const r = el.getBoundingClientRect()
    const br = box.getBoundingClientRect()
    if (r.bottom > br.top - 200 && r.top < br.bottom + 200) out.push(n)
  }
  return out
}

/**
 * 尺寸稳定前不许滚动改写页码。
 * 原因：初次打开时 slot 高度按「还没量到容器宽度」的 scale 算，`scrollIntoView`
 * 触发的 scroll 事件会据此把页码判成第 1 页 —— 表现就是「重新打开后进度丢失」。
 */
let settled = false

function onScroll(): void {
  if (!settled) return
  if (prefs.value.scrollMode === 'page') return
  const box = boxRef.value
  if (!box) return
  const br = box.getBoundingClientRect()
  // 当前页 = **视口顶部所在的页**（用户正在看的第一页）。
  // 不用视口中线：一屏约一页时中线会落到下一页，进度会莫名多一页。
  const line = br.top + 8
  let cur = 1
  for (const [n, el] of slots) {
    if (el.getBoundingClientRect().top <= line) cur = Math.max(cur, n)
  }
  if (cur !== page.value) {
    page.value = cur
    scheduleSave()
  }
}

function scheduleSave(): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void save(), 600)
}

async function save(): Promise<void> {
  if (!total.value) return
  const percent = Math.min(100, (page.value / total.value) * 100)
  try {
    await api.setProgress(props.bookId, page.value - 1, percent)
  } catch {
    /* 静默：离线或未登录时不打断阅读 */
  }
}

function go(n: number): void {
  const step = spreadOn.value ? 2 : 1
  page.value = Math.min(Math.max(1, n), total.value)
  void save()
  if (prefs.value.scrollMode === 'page') {
    void renderPage(page.value)
    if (spreadOn.value) void renderPage(page.value + step - 1)
  } else {
    slots.get(page.value)?.scrollIntoView({ block: 'start' })
  }
}

function next(): void {
  go(page.value + (spreadOn.value ? 2 : 1))
}
function prev(): void {
  go(page.value - (spreadOn.value ? 2 : 1))
}

function zoomBy(d: number): void {
  prefs.value.fit = 'custom'
  prefs.value.zoom = Math.min(3, Math.max(0.5, Math.round((prefs.value.zoom + d) * 4) / 4))
}

function onKeydown(e: KeyboardEvent): void {
  const step = spreadOn.value ? 2 : 1
  if (e.key === 'ArrowRight' || e.key === 'PageDown') go(page.value + step)
  else if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(page.value - step)
}

let ro: ResizeObserver | null = null

onMounted(async () => {
  try {
    const pdfjs: any = await import('pdfjs-dist')
    const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
    pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
    let token = ''
    try {
      token = localStorage.getItem('nf_token') || ''
    } catch {
      /* 隐私模式 */
    }
    pdfDoc = await pdfjs.getDocument({
      url: `/api/books/${encodeURIComponent(props.bookId)}/file`,
      // 走 /api/ 必须带 Bearer；pdf.js 支持自定义头，所以不需要 ?token= 口子
      httpHeaders: token ? { Authorization: `Bearer ${token}` } : {},
    }).promise
    total.value = pdfDoc.numPages
    const first = await pdfDoc.getPage(1)
    const vp = first.getViewport({ scale: 1 })
    base.value = { w: vp.width, h: vp.height }
    // 恢复进度
    try {
      const p = await api.getProgress(props.bookId)
      const n = Math.min(total.value, Math.max(1, (p.locator || 0) + 1))
      page.value = n
    } catch {
      /* 无进度则从第 1 页开始 */
    }
    loading.value = false
    await new Promise((r) => requestAnimationFrame(r))
    measure()
    if (prefs.value.scrollMode !== 'page') {
      // 滚动模式：先滚到目标页，再渲染可见页
      slots.get(page.value)?.scrollIntoView({ block: 'start' })
    }
    redraw()
    // 等一帧让 ResizeObserver 完成首轮测量（scale 会变），再对准一次目标页，
    // 然后才允许滚动事件改写页码 —— 否则恢复的进度会被首帧的错位滚动覆盖
    await new Promise((r) => setTimeout(r, 150))
    if (prefs.value.scrollMode !== 'page') slots.get(page.value)?.scrollIntoView({ block: 'start' })
    settled = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'PDF 打开失败'
    loading.value = false
  }

  if (typeof ResizeObserver === 'function' && boxRef.value) {
    ro = new ResizeObserver(() => {
      const keep = page.value
      measure()
      redraw()
      // 尺寸变化会改变 slot 高度 → 滚动位置漂移，按当前页重新对准
      if (settled && prefs.value.scrollMode !== 'page') slots.get(keep)?.scrollIntoView({ block: 'start' })
    })
    ro.observe(boxRef.value)
  }
  if (typeof IntersectionObserver === 'function') {
    io = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (!en.isIntersecting) continue
          const n = Number((en.target as HTMLElement).dataset.page || 0)
          if (n) void renderPage(n)
        }
      },
      { root: boxRef.value, rootMargin: '300px' },
    )
  }
  window.addEventListener('keydown', onKeydown)
})

function measure(): void {
  const el = boxRef.value
  if (!el) return
  boxW.value = el.clientWidth
  boxH.value = el.clientHeight
}

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  void save()
  window.removeEventListener('keydown', onKeydown)
  io?.disconnect()
  ro?.disconnect()
  try {
    pdfDoc?.destroy?.()
  } catch {
    /* ignore */
  }
})

// 布局相关偏好变化 → 重画（页展可能改变并排页数，缩放必然变）
watch([scale, () => prefs.value.scrollMode, () => prefs.value.spread], () => {
  if (total.value) redraw()
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
      <button type="button" class="cursor-pointer px-1.5 text-[13px] text-muted-foreground hover:text-foreground" @click="zoomBy(-0.25)">−</button>
      <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ Math.round(scale * 100) }}%</span>
      <button type="button" class="cursor-pointer px-1.5 text-[13px] text-muted-foreground hover:text-foreground" @click="zoomBy(0.25)">＋</button>

      <select
        v-model="prefs.fit"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="适配方式"
      >
        <option v-for="f in PDF_FITS" :key="f.key" :value="f.key">{{ f.label }}</option>
      </select>
      <select
        v-model="prefs.scrollMode"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="滚动模式"
      >
        <option v-for="m in PDF_SCROLL_MODES" :key="m.key" :value="m.key">{{ m.label }}</option>
      </select>
      <select
        v-model="prefs.spread"
        class="h-7 rounded-md border border-border bg-muted px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
        aria-label="页展"
      >
        <option v-for="s in PDF_SPREADS" :key="s.key" :value="s.key">{{ s.label }}</option>
      </select>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">
      正在加载 PDF（首次打开需下载渲染器）…
    </div>
    <div v-else-if="error" class="py-20 text-center text-[13px] text-destructive">{{ error }}</div>

    <!-- 画布区 -->
    <div
      v-show="!loading && !error"
      ref="boxRef"
      class="min-h-0 flex-1 overflow-auto bg-neutral-200/70 dark:bg-neutral-900/60"
      @scroll="onScroll"
    >
      <div
        class="flex min-h-full items-start justify-center gap-3 p-5"
        :class="prefs.scrollMode === 'horizontal' ? 'flex-row' : 'flex-col items-center'"
      >
        <template v-if="prefs.scrollMode === 'page'">
          <div v-for="n in shown" :key="n" :data-page="n" :ref="(el) => setSlot(n, el)" class="bg-white shadow-sm" :style="slotStyle(n)">
            <canvas :ref="(el) => setCanvas(n, el)" />
          </div>
        </template>
        <template v-else>
          <div
            v-for="n in total"
            :key="n"
            :data-page="n"
            :ref="(el) => setSlot(n, el)"
            class="shrink-0 bg-white shadow-sm"
            :style="slotStyle(n)"
          >
            <canvas :ref="(el) => setCanvas(n, el)" />
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
