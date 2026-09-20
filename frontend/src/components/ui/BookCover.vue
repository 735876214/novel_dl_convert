<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { api, type BookCard } from '@/lib/api'
import { useCoverPrefsStore, type CoverOverlay, type CoverSpine } from '@/stores/coverPrefs'

/**
 * 书封。显示方式 / 书脊 / 阴影 / 叠加层全部由「设置 → 封面样式」的偏好驱动
 * （`stores/coverPrefs`，存 localStorage）。
 *
 * 优先显示 EPUB 内嵌的**真实封面**（`GET /api/books/{id}/cover`）；
 * 没有封面或加载失败时回退到「c1/c2 渐变 + 书名」占位。
 *
 * ⚠️ 三种显示方式里，`fill` / `natural` 用的是照搬来的 cover-effects.css 里的
 * `.book-cover-artwork-frame--full` / `--natural`；
 * 但那份 CSS 只给了 `--natural` 的阴影与「surface 透明」，**几何要由组件补**（见下）。
 * `blurred` 上游没有对应类，是本项目自己实现的（模糊底图 + 居中完整封面）。
 */
type CoverBook = Pick<BookCard, 'title' | 'c1' | 'c2'> &
  Partial<Pick<BookCard, 'id' | 'has_cover' | 'percent' | 'format' | 'stars' | 'series'>>

const props = withDefaults(
  defineProps<{
    book: CoverBook
    /** 仅在**没有真实封面**时作为占位文字，否则会压在封面上 */
    showTitle?: boolean
    interactive?: boolean
    /**
     * 封面比例与圆角。默认竖版 3:4 圆角矩形；`circle` 供作者页的圆形头像用
     * （由「设置 → 外观 → Layout」的作者封面形状驱动）。
     */
    shape?: 'portrait' | 'circle'
  }>(),
  { showTitle: true, interactive: true, shape: 'portrait' },
)

const prefs = useCoverPrefsStore()

/** 加载失败后不再重试（避免坏图反复触发 onerror），直接走占位 */
const failed = ref(false)

const src = computed(() =>
  props.book.id && props.book.has_cover ? api.coverUrl(props.book.id) : '',
)

// 列表复用组件实例时若换了书，重置失败态，否则新书会沿用上一本的失败结论
watch(
  () => props.book.id,
  () => {
    failed.value = false
  },
)

const showImg = computed(() => Boolean(src.value) && !failed.value)
const mode = computed(() => prefs.prefs.display)
const spine = computed(() => prefs.prefs.spine)

/**
 * 实际生效的书脊：漫画（CBZ / CBR）受「漫画书脊」开关控制（第 20 期）。
 * 该开关默认开着 → 与加它之前**完全一致**（此前漫画与电子书共用同一个 spine 设置）。
 */
const spineMode = computed<CoverSpine>(() => {
  const fmt = String(props.book.format || '').toUpperCase()
  if ((fmt === 'CBZ' || fmt === 'CBR') && !prefs.prefs.spineComics) return 'off'
  return prefs.prefs.spine
})

function has(o: CoverOverlay): boolean {
  return prefs.prefs.overlays.includes(o)
}

/**
 * CSS 只提供 normal / strong 两档阴影，**没有 off 档**，
 * 所以「关闭」用内联覆盖变量实现（`.book-cover-surface` 自己就有 box-shadow）。
 */
const styleVars = computed<Record<string, string>>(() => {
  const vars: Record<string, string> = {}
  if (prefs.prefs.shadow === 'off') {
    vars['--book-cover-shadow'] = 'none'
    vars['--book-cover-shadow-hover'] = 'none'
  }
  return vars
})

/** 自然比例：frame 贴住卡片底边（CSS 未给定位，这里补上） */
const natural = computed(() => mode.value === 'natural')

const statusLabel = computed(() => {
  const p = props.book.percent ?? 0
  if (p >= 99.5) return '已读完'
  return p > 0 ? '在读' : '未读'
})
</script>

<template>
  <div
    class="book-cover-surface relative w-full overflow-hidden transition-transform duration-200 ease-out"
    :class="[
      shape === 'circle' ? 'aspect-square rounded-full' : 'aspect-3/4 rounded-md',
      interactive ? 'group-hover:-translate-y-0.5' : '',
    ]"
    :data-cover-spine="spineMode === 'off' ? undefined : spineMode"
    :data-cover-shadow="prefs.prefs.shadow === 'strong' ? 'strong' : undefined"
    :data-cover-fit="natural ? 'natural-bottom' : undefined"
    :style="[{ backgroundImage: `linear-gradient(160deg, ${book.c1}, ${book.c2})` }, styleVars]"
  >
    <!-- 模糊底图：同一张封面铺满并模糊，中间再放完整版 -->
    <img
      v-if="showImg && mode === 'blurred'"
      :src="src"
      class="absolute inset-0 h-full w-full scale-110 object-cover opacity-70 blur-lg"
      aria-hidden="true"
      alt=""
    >

    <!-- 封面本体 -->
    <div
      v-if="showImg"
      class="book-cover-artwork-frame"
      :class="natural ? 'book-cover-artwork-frame--natural inset-x-0 bottom-0' : 'book-cover-artwork-frame--full'"
    >
      <img
        :src="src"
        :alt="book.title"
        loading="lazy"
        decoding="async"
        class="w-full"
        :class="mode === 'fill' ? 'h-full object-cover' : 'h-auto object-contain'"
        @error="failed = true"
      >
    </div>

    <!-- 书脊覆盖层：与 surface 用同一个取值，CSS 分别读两处 -->
    <div
      class="book-cover-spine-layer absolute inset-0"
      :data-cover-spine="spineMode === 'off' ? undefined : spineMode"
    />

    <!-- 占位文字（只在没有真实封面时出现） -->
    <span
      v-if="showTitle && !showImg"
      class="absolute inset-0 z-2 flex items-center p-2 text-center font-serif text-[13px] leading-snug font-semibold text-white/92"
      style="text-shadow: 0 1px 2px oklch(0 0 0 / 0.35)"
    >
      {{ book.title }}
    </span>

    <!-- 叠加层 -->
    <span
      v-if="has('series') && book.series"
      class="absolute inset-x-0 top-0 z-3 truncate bg-black/55 px-1.5 py-0.5 text-[10px] text-white"
    >
      {{ book.series }}
    </span>

    <span
      v-if="has('stars') && (book.stars ?? 0) > 0"
      class="absolute top-1 left-1 z-3 rounded bg-black/55 px-1.5 py-0.5 text-[10px] tracking-tight text-amber-300"
    >
      {{ '★'.repeat(book.stars ?? 0) }}
    </span>

    <span
      v-if="has('format') && book.format"
      class="absolute top-1 right-1 z-3 rounded bg-black/55 px-1.5 py-0.5 font-mono text-[9.5px] text-white"
    >
      {{ book.format }}
    </span>

    <span
      v-if="has('status')"
      class="absolute bottom-1 left-1 z-3 rounded bg-black/55 px-1.5 py-0.5 text-[9.5px] text-white"
    >
      {{ statusLabel }}
    </span>

    <div v-if="has('progress')" class="absolute inset-x-0 bottom-0 z-3 h-1 bg-black/35">
      <div class="h-full bg-primary" :style="{ width: `${book.percent ?? 0}%` }" />
    </div>
  </div>
</template>
