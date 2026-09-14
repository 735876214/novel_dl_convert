<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 单书详情：面包屑 + hero + 四标签（概览 / 目录 / 文件 / 批注）。
 *
 * 目录使用结构化的卷/章演示数据（SANTI_VOLUMES），与 v2 一致 —— 真实书库接入后
 * 这里应改为按书 id 取实际章节树。
 */
const route = useRoute()
const router = useRouter()
const library = useLibraryStore()
const ui = useUiStore()

const bookId = computed(() => Number(route.params.id))
const book = computed(() => library.findBook(bookId.value))

const TABS = [
  { id: 'overview', label: '概览' },
  { id: 'chapters', label: '目录' },
  { id: 'files', label: '文件' },
  { id: 'annotations', label: '批注' },
] as const

const tab = ref<(typeof TABS)[number]['id']>('overview')

const descOpen = ref(false)
const chapterQuery = ref('')

/** 星级：rating 满分 10，折算 5 星 */
const stars = computed(() => Math.round(((book.value?.rating ?? 0) / 10) * 5))

const chapterCount = computed(() =>
  library.santiVolumes.reduce((sum, v) => sum + v.chapters.length, 0),
)

/** 章节过滤：输入时只切行显隐，不重建列表 */
const volumes = computed(() => {
  const q = chapterQuery.value.trim().toLowerCase()
  if (!q) return library.santiVolumes
  return library.santiVolumes
    .map((v) => ({ ...v, chapters: v.chapters.filter((c) => c.title.toLowerCase().includes(q)) }))
    .filter((v) => v.chapters.length > 0)
})

const collapsedVolumes = ref<Record<string, boolean>>({})

function toggleVolume(name: string): void {
  collapsedVolumes.value[name] = !collapsedVolumes.value[name]
}

function demo(label: string): void {
  ui.demo(label)
}
</script>

<template>
  <div v-if="book">
    <!-- 面包屑 -->
    <nav class="mb-4 flex items-center gap-1.5 text-[12px] text-muted-foreground">
      <button type="button" class="cursor-pointer transition-colors hover:text-primary" @click="router.push('/shelf')">
        书库
      </button>
      <span class="opacity-50">/</span>
      <span>{{ library.shelfTitle }}</span>
      <span class="opacity-50">/</span>
      <span class="text-foreground">{{ book.title }}</span>
    </nav>

    <!-- hero -->
    <div class="mb-6 flex flex-col gap-5 sm:flex-row sm:gap-7">
      <div class="relative w-[140px] shrink-0 sm:w-[176px]">
        <BookCover :book="book" :interactive="false" :show-title="false" />
        <!-- 进度胶囊叠在封面右下角 -->
        <div class="absolute -right-1.5 -bottom-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[11.5px] font-semibold text-foreground tabular-nums shadow-sm">
          {{ book.progress }}%
        </div>
      </div>

      <div class="min-w-0 flex-1">
        <div class="mb-2 flex flex-wrap items-center gap-1.5">
          <Badge v-if="book.series" tone="accent">{{ book.series }} ①</Badge>
          <Badge v-for="t in book.tags.slice(0, 3)" :key="t">{{ t }}</Badge>
        </div>

        <h1 class="font-serif text-[26px] leading-tight font-bold tracking-tight text-foreground">
          {{ book.title }}
        </h1>
        <p class="mt-1 text-[13px] text-muted-foreground">{{ book.author }} · {{ book.year }} 年</p>

        <div class="mt-2.5 flex flex-wrap items-center gap-2">
          <span class="flex items-center gap-0.5">
            <svg
              v-for="i in 5"
              :key="i"
              viewBox="0 0 24 24"
              class="h-3.5 w-3.5"
              :class="i <= stars ? 'fill-star-highlight text-star-highlight' : 'fill-muted text-muted'"
            >
              <path d="M12 3l2.7 5.4 6 .8-4.3 4.2 1 6-5.4-2.8-5.4 2.8 1-6L3.3 9.2l6-.8z" />
            </svg>
          </span>
          <span class="text-[13px] font-semibold text-foreground tabular-nums">{{ book.rating }}</span>
          <span class="text-[11.5px] text-muted-foreground tabular-nums">12,847 人评分</span>
        </div>

        <p class="mt-2 text-[12px] text-muted-foreground">
          {{ book.words }} · {{ book.pages }} 页 · 中文 · ISBN {{ book.isbn }}
        </p>

        <div class="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="primary" @click="demo(`继续阅读《${book.title}》`)">
            <Icon name="play" class="h-3.5 w-3.5" />继续阅读
          </Button>
          <Button variant="ghost" @click="demo(`下载《${book.title}》`)">
            <Icon name="download" class="h-3.5 w-3.5" />下载
          </Button>
          <Button variant="ghost" @click="demo(`转换《${book.title}》`)">
            <Icon name="convert" class="h-3.5 w-3.5" />转换
          </Button>
          <Button variant="ghost" @click="demo('加入收藏')">
            <Icon name="star" class="h-3.5 w-3.5" />收藏
          </Button>
        </div>
      </div>
    </div>

    <!-- 标签栏 -->
    <div class="mb-4 flex items-center gap-1 border-b border-border">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        :title="t.label"
        class="relative cursor-pointer px-3 py-2 text-[13px] font-medium transition-colors"
        :class="tab === t.id ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'"
        @click="tab = t.id"
      >
        {{ t.label }}
        <span v-if="t.id === 'chapters'" class="ml-1 text-[11px] text-muted-foreground tabular-nums">{{ chapterCount }}</span>
        <span
          v-if="tab === t.id"
          class="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
        />
      </button>
    </div>

    <!-- ============ 概览 ============ -->
    <div v-show="tab === 'overview'" class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <Card class="lg:col-span-2">
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">制版说明</h3>
        <p class="text-[12.5px] leading-relaxed text-muted-foreground" :class="descOpen ? '' : 'line-clamp-4'">
          {{ book.desc }}
        </p>
        <button
          type="button"
          class="mt-1.5 cursor-pointer text-[11.5px] text-primary"
          @click="descOpen = !descOpen"
        >
          {{ descOpen ? '收起' : '展开全文' }}
        </button>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">版本信息</h3>
        <dl class="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
          <div v-for="item in [
            { k: '系列', v: book.series ?? '独立作品' },
            { k: '出版年', v: `${book.year} 年` },
            { k: '出版社', v: book.publisher },
            { k: '页数', v: String(book.pages) },
            { k: '字数', v: book.words },
            { k: '语言', v: '中文' },
          ]" :key="item.k">
            <dt class="text-[11px] text-muted-foreground">{{ item.k }}</dt>
            <dd class="mt-0.5 truncate text-[12.5px] text-foreground">{{ item.v }}</dd>
          </div>
        </dl>
      </Card>

      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">阅读进度</h3>
        <div class="mb-3 flex items-end gap-2">
          <span class="font-serif text-[24px] leading-none font-bold text-foreground tabular-nums">{{ book.progress }}%</span>
          <span class="pb-0.5 text-[11.5px] text-muted-foreground">第 28 章 / 共 88 章</span>
        </div>
        <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div class="h-full rounded-full bg-primary transition-[width] duration-500" :style="{ width: `${book.progress}%` }" />
        </div>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">成品文件</h3>
        <div class="flex flex-col gap-1.5">
          <div
            v-for="f in library.bookFiles"
            :key="f.format"
            class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
          >
            <span class="text-[11px] font-semibold text-foreground">{{ f.format }}</span>
            <span class="text-[11.5px] text-muted-foreground">{{ f.size }} · {{ f.quality }}</span>
            <Badge v-if="f.current" tone="ok" class="ml-auto">当前</Badge>
            <span v-else class="ml-auto text-[11px] text-muted-foreground">{{ f.date }}</span>
          </div>
        </div>

        <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">供纸来源</h3>
        <div class="flex flex-col gap-1.5">
          <div v-for="s in book.sources" :key="s.name" class="flex items-center gap-2">
            <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="s.ok ? 'bg-success' : 'bg-destructive'" />
            <span class="text-[12.5px] text-foreground">{{ s.name }}</span>
            <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">{{ s.chapters }} 章</span>
          </div>
        </div>
      </Card>
    </div>

    <!-- ============ 目录 ============ -->
    <div v-show="tab === 'chapters'">
      <div class="mb-3 flex items-center gap-2.5">
        <div class="relative max-w-[22rem] flex-1">
          <Icon name="search" class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="chapterQuery"
            type="text"
            placeholder="搜索章节…"
            aria-label="搜索章节"
            class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
        </div>
        <span class="text-[11.5px] text-muted-foreground tabular-nums">
          共 {{ volumes.reduce((s, v) => s + v.chapters.length, 0) }} 章
        </span>
      </div>

      <Card v-for="v in volumes" :key="v.name" padding="none" class="mb-2">
        <button
          type="button"
          class="flex w-full cursor-pointer items-center gap-2.5 px-3.5 py-2.5 text-left"
          @click="toggleVolume(v.name)"
        >
          <Icon
            name="chev"
            class="h-3.5 w-3.5 text-muted-foreground transition-transform"
            :class="collapsedVolumes[v.name] ? '-rotate-90' : ''"
          />
          <span class="text-[12.5px] font-semibold text-foreground">{{ v.name }}</span>
          <span class="text-[11px] text-muted-foreground tabular-nums">{{ v.chapters.length }} 章</span>
        </button>

        <div v-show="!collapsedVolumes[v.name]" class="border-t border-border">
          <div
            v-for="c in v.chapters"
            :key="c.num"
            class="flex items-center gap-2.5 border-b border-border/60 px-3.5 py-1.5 last:border-b-0"
            :class="c.current ? 'bg-[var(--shell-accent-wash)]' : ''"
          >
            <span class="w-8 shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ c.num }}</span>
            <span class="min-w-0 flex-1 truncate text-[12.5px]" :class="c.current ? 'font-semibold text-primary' : 'text-foreground'">
              {{ c.title }}
            </span>
            <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ c.words }} 字</span>
            <Icon v-if="c.read" name="check" class="h-3.5 w-3.5 shrink-0 text-success" />
          </div>
        </div>
      </Card>

      <EmptyState v-if="!volumes.length" icon="search" title="没有匹配的章节" desc="换个关键词再试。" />
    </div>

    <!-- ============ 文件 ============ -->
    <div v-show="tab === 'files'">
      <Card padding="none">
        <div
          v-for="f in library.bookFiles"
          :key="f.format"
          class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
        >
          <span class="grid h-8 w-11 shrink-0 place-items-center rounded-sm bg-muted text-[11px] font-semibold text-foreground">
            {{ f.format }}
          </span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[12.5px] font-medium text-foreground">{{ book.title }}.{{ f.format.toLowerCase() }}</div>
            <div class="text-[11px] text-muted-foreground">{{ f.size }} · {{ f.quality }} · {{ f.date }}</div>
          </div>
          <Badge v-if="f.current" tone="ok">当前版本</Badge>
          <Button size="sm" @click="demo(`下载 ${f.format}`)">下载</Button>
        </div>
      </Card>
    </div>

    <!-- ============ 批注 ============ -->
    <div v-show="tab === 'annotations'">
      <EmptyState
        icon="pencil"
        title="这本书还没有注释"
        desc="划线、笔记与摘录会在这里按时间轴汇总（含 12 个月热力图）。"
      />
    </div>
  </div>

  <EmptyState v-else icon="alert" title="找不到这本书" desc="它可能已被移除，或链接有误。">
    <template #action>
      <Button variant="primary" @click="router.push('/shelf')">回到书库</Button>
    </template>
  </EmptyState>
</template>
