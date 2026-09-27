<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import ProgressBar from '@/components/ui/ProgressBar.vue'
import RatingStars from '@/components/ui/RatingStars.vue'
import { api, type BookCard, type ProgressState } from '@/lib/api'
import { statusLabelOf } from '@/lib/readingThresholds'
import { useCollectionsStore } from '@/stores/collections'
import { useLibraryStore } from '@/stores/library'

/**
 * 详情页顶部：封面 + 标题区 + 操作行（第 63 期从 `BookDetailView` 抽出并重排）。
 *
 * 重排对齐样板（Book Orbit 详情页）的三条：**进度上提到 hero**（此前只在概览标签的
 * 一张卡里，翻到别的标签就看不见读到哪了）、**星级上提到 hero**（评分是「我对这本书
 * 的结论」，属于首屏信息）、**状态 / 格式并排成徽章**。
 *
 * 收藏夹那套交互内聚在这里：它只在操作行里出现，抽出去反而要来回传 6 个 ref。
 */
const props = defineProps<{
  book: BookCard
  progress: ProgressState | null
  canStart: boolean
  /** 有声书：主按钮文案与去处都不同（播放器 vs 阅读器） */
  canListen: boolean
  /** 有没有可下载的成品文件 —— 没有就把下载按钮禁掉，而不是留一个点了没反应的按钮 */
  hasFiles: boolean
  /** 封面取色变量；取不到（无封面 / 关闭取色）时传 undefined，CSS 那条 hsl() 整条失效 */
  tintStyle?: Record<string, string>
  tinted: boolean
}>()

const emit = defineEmits<{ start: []; download: [] }>()

const library = useLibraryStore()
const collections = useCollectionsStore()

const menuOpen = ref(false)
const inCollections = ref<number[]>([])
const newCollection = ref('')

/** 「作者 · 年份」——两者都没值就整行不渲染（不摆「未知 · 未知 年」） */
const byline = computed(() =>
  [props.book.author, props.book.year].filter(Boolean).join(' · '),
)

/** 「语言 · 出版社」同理 */
const imprint = computed(() =>
  [props.book.language, props.book.publisher].filter(Boolean).join(' · '),
)

/**
 * 状态文案与封面角标**同源**（`statusLabelOf`，第 41 期统一）—— 有状态行就以它为权威，
 * 没有才按进度阈值兜底。跨库组件拿当前库阈值当上下文。
 */
const statusLabel = computed(() => statusLabelOf(props.book, library.currentLibraryId))

const percent = computed(() => props.progress?.percent ?? 0)
const stars = computed(() => props.book.stars ?? 0)

/** 读完用 ok 色，其余用主色 */
const progressTone = computed(() => (percent.value >= 100 ? 'ok' : 'primary'))

async function loadBookCollections(): Promise<void> {
  try {
    inCollections.value = (await api.bookCollections(props.book.id)).items
  } catch {
    /* ignore */
  }
}

async function toggleCollection(cid: number): Promise<void> {
  const has = inCollections.value.includes(cid)
  try {
    if (has) await api.removeFromCollection(cid, props.book.id)
    else await api.addToCollection(cid, props.book.id)
    inCollections.value = has
      ? inCollections.value.filter((x) => x !== cid)
      : [...inCollections.value, cid]
    await collections.load(true)
  } catch {
    /* ignore */
  }
}

async function createAndAdd(): Promise<void> {
  const name = newCollection.value.trim()
  if (!name) return
  try {
    const cid = await collections.create(name)
    await api.addToCollection(cid, props.book.id)
    inCollections.value = [...inCollections.value, cid]
    newCollection.value = ''
    await collections.load(true)
  } catch {
    /* ignore */
  }
}

onMounted(loadBookCollections)
</script>

<template>
  <!-- 背景取封面主色染色（取不到就不染色，见 tint / coverTint.ts） -->
  <div
    class="mb-6 flex flex-col gap-5 sm:flex-row sm:gap-7"
    :class="tinted ? 'book-detail-cover-tint' : ''"
    :style="tintStyle"
  >
    <div class="relative w-[140px] shrink-0 sm:w-[176px]">
      <BookCover :book="book" :interactive="false" :show-title="false" />
    </div>

    <div class="min-w-0 flex-1">
      <div class="mb-2 flex flex-wrap items-center gap-1.5">
        <Badge v-if="book.series" tone="accent">{{ book.series }}</Badge>
        <Badge v-for="t in (book.tags || []).slice(0, 3)" :key="t">{{ t }}</Badge>
      </div>

      <h1 class="font-serif text-[26px] leading-tight font-bold tracking-tight text-foreground">
        {{ book.title }}
      </h1>
      <p v-if="byline" class="mt-1 text-[13px] text-muted-foreground">{{ byline }}</p>

      <!-- 评分：0 星 = 未评分 → 整块不渲染（画五颗灰星会被读成「打了 0 分」） -->
      <div v-if="stars > 0" class="mt-2 flex items-center gap-2">
        <RatingStars :model-value="stars" readonly size="sm" />
        <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ stars }} / 5</span>
      </div>

      <div class="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone="neutral">{{ statusLabel }}</Badge>
        <Badge v-if="book.format" tone="neutral">{{ book.format }}</Badge>
        <span v-if="imprint" class="text-[12px] text-muted-foreground">{{ imprint }}</span>
      </div>

      <!-- 进度：>0 才显示。0% 与「没读过」在这里是同一个结论，不显示两条 -->
      <div v-if="percent > 0" data-test="hero-progress" class="mt-3 max-w-[24rem]">
        <ProgressBar :value="percent" :tone="progressTone" />
        <p class="mt-1 text-[11.5px] text-muted-foreground tabular-nums">
          已读 {{ Math.round(percent) }}%
        </p>
      </div>

      <div class="mt-4 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          :disabled="!canStart"
          :title="canStart
            ? (canListen ? '进入播放器' : '进入阅读器')
            : 'EPUB / TXT（含章节）/ PDF / 漫画 / 有声书可在线打开'"
          @click="emit('start')"
        >
          <Icon name="play" class="h-3.5 w-3.5" />
          {{ percent > 0
            ? (canListen ? '继续播放' : '继续阅读')
            : (canListen ? '开始播放' : '开始阅读') }}
        </Button>
        <Button
          variant="ghost"
          :disabled="!hasFiles"
          :title="hasFiles ? '下载第一份成品文件' : '这本书还没有可下载的文件'"
          @click="emit('download')"
        >
          <Icon name="download" class="h-3.5 w-3.5" />下载
        </Button>

        <!-- 加入收藏：勾选加入 / 移除，或就地新建收藏夹 -->
        <div class="relative">
          <Button variant="ghost" @click="menuOpen = !menuOpen">
            <Icon name="star" class="h-3.5 w-3.5" />收藏
            <span v-if="inCollections.length" class="text-[11px] text-muted-foreground tabular-nums">
              {{ inCollections.length }}
            </span>
          </Button>

          <div
            v-if="menuOpen"
            class="absolute left-0 z-20 mt-1 w-60 rounded-lg border border-border bg-card p-2 shadow-lg"
          >
            <p v-if="!collections.items.length" class="px-1.5 py-1 text-[11.5px] text-muted-foreground">
              还没有收藏夹，先在下方新建一个。
            </p>
            <button
              v-for="c in collections.items"
              :key="c.id"
              type="button"
              class="flex w-full cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-[12.5px] text-foreground transition-colors hover:bg-muted"
              @click="toggleCollection(c.id)"
            >
              <Icon
                :name="inCollections.includes(c.id) ? 'check' : 'plus'"
                class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
              />
              <span class="min-w-0 flex-1 truncate">{{ c.name }}</span>
              <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ c.count }}</span>
            </button>

            <div class="mt-1 flex items-center gap-1.5 border-t border-border pt-2">
              <input
                v-model="newCollection"
                type="text"
                placeholder="新建收藏夹…"
                class="h-7 min-w-0 flex-1 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
                @keyup.enter="createAndAdd"
              >
              <Button size="sm" :disabled="!newCollection.trim()" @click="createAndAdd">新建</Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
