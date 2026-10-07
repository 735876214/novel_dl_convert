<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Icon from '@/components/ui/Icon.vue'
import { MAX_COVERS_PER_ROW, type ShelfDef, type ShelfType } from '@/data/dashboard'
import type { BookCard } from '@/lib/api'
import { openTargetOf } from '@/lib/bookOpen'
import { filterByLibraries } from '@/lib/shelfScope'
import {
  chunkIntoBands,
  coverDelayMs,
  effectiveShelfRows,
  shelfBookLimit,
} from '@/lib/shelfRows'
import { useNarrowScreenOnMount } from '@/lib/viewport'
import { useLibraryStore } from '@/stores/library'

/**
 * 书架行（对应 BookOrbit 的 `DashboardScroller` —— ⚠️ 名字相同但职责不同：
 * 上游那个文件是「一个书架行」，本项目原来是页面级栅格容器
 * `DashboardScroller.vue`；第 82 期把页面容器直接写进 `DashboardView.vue` 后，
 * 那个同名组件已删除，**本文件才是与上游 `DashboardScroller` 对应的实现**）。
 *
 * 第 82 期：套卡片外壳（与部件卡同款）+ 表头（图标块 / 计数胶囊 / 悬停滚动按钮）
 * + 多行分带（`rows` 1..3，窄屏压到 2）+ 加载骨架。
 * 第 83 期：「库范围」过滤（`shelf.library_ids`，空 = 全部书库）叠在 `allBooks` 之后 ——
 * 四种行类型统一受益，`scope`（智能书架筛选键）与它是两个维度。
 * 第 108 期：点封面**直接读**（用户口径）—— 撤掉了第 83 期的快速预览浮层，
 * 仪表盘只做快速启动器；判断收在 `openBook` 一处（`openTargetOf` + 详情页兜底）。
 * 业务语义不动：四种类型的数据来源、继续阅读的进度条、「查看全部」的目标都保持现状。
 */
const props = defineProps<{ shelf: ShelfDef }>()

const library = useLibraryStore()
const router = useRouter()

// 书目与书库列表都要：前者是行内数据源，后者是「库范围」的候选与「哪些 id 还有效」的判据
onMounted(() => {
  library.loadBooks()
  library.loadLibraries()
})

const narrow = useNarrowScreenOnMount()

/** 行数：宽屏按配置（1..3），窄屏最多 2 行 */
const shelfRows = computed(() => effectiveShelfRows(props.shelf.rows ?? 1, narrow.value))

/** 该书架要取的封面总数（每行 20 本 × 行数，硬上限兜底） */
const fetchLimit = computed(() => shelfBookLimit(MAX_COVERS_PER_ROW, shelfRows.value, 50))

/**
 * 「随机发现」改为确定性排序：按 book id 稳定升序，刷新页面顺序固定、无运行时随机。
 * 用 computed 依赖 library.books，仅在数据变化时重算。
 */
const discoverBooks = computed<BookCard[]>(() =>
  [...library.books].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
)

const allBooks = computed<BookCard[]>(() => {
  switch (props.shelf.type) {
    case 'continue':
      return library.continueReading
    case 'discover':
      return discoverBooks.value
    case 'recent':
      return [...library.books].sort((a, b) => (b.mtime || 0) - (a.mtime || 0))
    case 'scope':
      return props.shelf.scope ? library.smartBooks(props.shelf.scope) : library.books
    default:
      return library.books
  }
})

/** 书库列表的 id（判「哪些库范围 id 还有效」的唯一依据） */
const knownLibraryIds = computed(() => library.libraryEntities.map((l) => l.id))

/**
 * 「库范围」过滤：叠在 `allBooks` 之后 ⇒ 四种行类型统一生效。
 * 判定全部收在 `lib/shelfScope.ts`（空 = 全部；指向已删库的 id 忽略；有效项全无 ⇒ 退化为全部）。
 */
const scopedBooks = computed(() =>
  filterByLibraries(allBooks.value, props.shelf.library_ids, knownLibraryIds.value),
)

const visibleBooks = computed(() => scopedBooks.value.slice(0, fetchLimit.value))

/** 多行分带（rows = 1 时只有一带，渲染与改造前逐字节等价） */
const bands = computed(() => chunkIntoBands(visibleBooks.value, shelfRows.value))

/** 数据态：书库书目没回来 = 加载中（library 无 error 字段） */
const loading = computed(() => !library.loaded)
const empty = computed(() => !loading.value && visibleBooks.value.length === 0)

/**
 * 空是「被库范围筛掉了」还是「本来就没有」——两种空态的说法不同，
 * 否则用户看到空行会以为是数据没了（其实是自己设的范围）。
 */
const emptyByScope = computed(() => empty.value && allBooks.value.length > 0)

/** 书架类型的表头图标（走 lib/icons.ts 的注册表，不散落内联 SVG） */
const SHELF_TYPE_ICON: Record<ShelfType, string> = {
  continue: 'book',
  recent: 'sparkle',
  discover: 'star',
  scope: 'search',
}

const scrollEl = ref<HTMLElement | null>(null)

function scrollBy(delta: number): void {
  scrollEl.value?.scrollBy({ left: delta, behavior: 'smooth' })
}

/** 进度百分比（夹到 0–100；缺值当 0） */
function pct(b: BookCard): number {
  return Math.min(100, Math.max(0, Number(b.percent ?? 0)))
}

/** 「查看全部」：继续阅读行跳到「在读」智能书架，其余按标题进书库页 */
function openAll(): void {
  if (props.shelf.type === 'continue') library.openSmart('在读', 'reading')
  else library.openShelf(props.shelf.title)
  router.push('/shelf')
}

/**
 * 点封面 = **直接读**（第 108 期，用户口径）。
 *
 * 原是「先弹一层快速预览浮层」（第 83 期），多一次点击才进得去正文。现在照抄
 * `CurrentlyReadingWidget` 的判据（`openTargetOf`）：能读的直进阅读器 / 听书器，
 * **读不了的（如未归一成书的 ZIP 容器）进详情页** —— 不能出现「点了没反应」。
 *
 * ⚠️ 浮层里那四个动作（加入收藏 / 编辑元数据 / 移动到书库 / 删除）随之从仪表盘退场：
 * 仪表盘按用户口径只做**快速启动器**，这些管理动作书架页（仍在用同一个浮层）与
 * 详情页各自都有。**别再往封面上挂第二个按钮**把浮层请回来。
 */
function openBook(b: BookCard): void {
  void router.push(openTargetOf(b)?.to ?? `/book/${b.id}`)
}
</script>

<template>
  <section
    class="group/shelf min-w-0 overflow-hidden rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]"
  >
    <!-- 表头：图标块 + 标题 + 计数胶囊 + （查看全部）+ 悬停滚动按钮 -->
    <div class="flex items-center justify-between px-4 pt-3.5">
      <div class="flex min-w-0 items-center gap-2.5">
        <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-muted/50">
          <Icon :name="SHELF_TYPE_ICON[shelf.type]" class="h-3.5 w-3.5 text-foreground" />
        </div>
        <h2 class="truncate text-[15px] font-bold tracking-tight text-foreground">{{ shelf.title }}</h2>
        <span
          v-if="!loading && visibleBooks.length"
          class="shrink-0 rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] font-bold text-foreground tabular-nums"
        >
          {{ visibleBooks.length }}
        </span>
      </div>

      <div class="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          class="flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-1 text-[11.5px] text-primary transition-colors hover:bg-muted"
          @click="openAll"
        >
          查看全部
          <Icon name="arrowRight" class="h-3 w-3" />
        </button>
        <div
          class="flex items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover/shelf:opacity-100"
        >
          <button
            type="button"
            aria-label="向左滚动"
            class="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            @click="scrollBy(-560)"
          >
            <Icon name="chevronLeft" class="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="向右滚动"
            class="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            @click="scrollBy(560)"
          >
            <Icon name="chevronRight" class="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>

    <!-- 加载中：与卡片带同形状的脉冲骨架（按行数分带，避免布局跳动） -->
    <div v-if="loading" class="flex flex-col gap-5 overflow-hidden px-4 pb-4 pt-2">
      <div v-for="band in shelfRows" :key="band" class="flex gap-3">
        <div v-for="n in 8" :key="n" class="w-[104px] shrink-0">
          <div class="w-full animate-pulse rounded-lg bg-muted" style="aspect-ratio: 2 / 3" />
        </div>
      </div>
    </div>

    <!-- 空：图标 + 一句话 -->
    <div v-else-if="empty" class="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
        <Icon :name="SHELF_TYPE_ICON[shelf.type]" class="h-5 w-5 text-muted-foreground" />
      </div>
      <p class="text-[12.5px] text-muted-foreground">
        {{ emptyByScope ? '所选书库里，这一行暂时没有书' : '这一行暂时没有书' }}
      </p>
      <p v-if="emptyByScope" class="text-[11px] text-muted-foreground">
        可在「自定义 → 书架」里调整该行的「库范围」
      </p>
    </div>

    <!-- 封面带：多行分带纵向堆叠，横向滚动 -->
    <div v-else ref="scrollEl" class="no-scrollbar overflow-x-auto px-4 pb-4 pt-2">
      <div class="flex w-max flex-col gap-5">
        <div v-for="(band, bandIndex) in bands" :key="bandIndex" class="flex items-end gap-3">
          <button
            v-for="(b, index) in band"
            :key="b.id"
            type="button"
            class="shelf-cover-enter w-[104px] shrink-0 cursor-pointer text-left"
            :style="{ animationDelay: `${coverDelayMs(index)}ms` }"
            @click="openBook(b)"
          >
            <div class="relative">
              <BookCover :book="b" />
              <!--
                继续阅读行显示进度（第 61 期）：封面底部细条 + 下方百分比。
                只在这一行显示 —— 其它行（最近添加 / 发现）的百分比没有意义。
              -->
              <div
                v-if="shelf.type === 'continue'"
                class="absolute inset-x-1 bottom-1 h-1 overflow-hidden rounded-full bg-black/45"
              >
                <div class="h-full rounded-full bg-primary" :style="{ width: `${pct(b)}%` }" />
              </div>
            </div>
            <div class="mt-1.5 truncate text-[12px] font-medium text-foreground">{{ b.title }}</div>
            <div class="flex items-baseline gap-1">
              <span class="truncate text-[11px] text-muted-foreground">{{ b.author }}</span>
              <span
                v-if="shelf.type === 'continue'"
                class="ml-auto shrink-0 text-[10.5px] text-muted-foreground tabular-nums"
              >
                {{ Math.round(pct(b)) }}%
              </span>
            </div>
          </button>
        </div>
      </div>
    </div>

  </section>
</template>

<style scoped>
/* 封面逐张错峰入场（第 83 期对齐 BookOrbit 的 dashboardFadeUp + index*35ms） */
@keyframes shelfCoverFadeUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.shelf-cover-enter {
  animation: shelfCoverFadeUp 0.35s ease both;
}

/*
  ⚠️ scoped keyframes **不受** `main.css` 里那条全局 `prefers-reduced-motion` 降级保护
  （那条只改 duration，靠的是全局选择器，而这里需要的是「干脆不播」）——
  系统开了「减少动态效果」就整段关掉，别只把时长压到 0.001ms 留一个闪动。
*/
@media (prefers-reduced-motion: reduce) {
  .shelf-cover-enter {
    animation: none !important;
  }
}
</style>
