<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import { api, type AuthorItem } from '@/lib/api'
import { useDisplayPrefsStore } from '@/stores/displayPrefs'

/** 作者总览：按 EPUB 元数据里的 author 聚合（见 library.authors_list）。
 *  有头像的作者显示抓取到的真实头像（网络头像已本地缓存），否则沿用书封占位。
 *  前端排序（书量 / 姓名）+「2+ 本」+「本周新增」筛选。 */
const router = useRouter()
const items = ref<AuthorItem[]>([])
const loading = ref(true)

/**
 * 作者封面尺寸 / 形状来自「设置 → 外观 → Layout」（上游该页的作者网格组）。
 * ⚠️ store 实例叫 `displayPrefs` 而不是 `display` —— 后者已被下面那个
 * 「筛选后的作者列表」computed 占用。
 */
const displayPrefs = useDisplayPrefsStore()
const coverShape = computed(() => displayPrefs.prefs.authorCoverShape)

/** 与书架网格同源（都吃 `gridGap`），只是行距按改造前的 16:24 比例放大 —— 作者卡封面下还有姓名与书量两行 */
const authorGridStyle = computed(() => ({
  gridTemplateColumns: `repeat(auto-fill, minmax(${displayPrefs.prefs.authorCoverSize}px, 1fr))`,
  columnGap: `${displayPrefs.prefs.gridGap}px`,
  rowGap: `${displayPrefs.prefs.gridGap * 1.5}px`,
}))

const sortMode = ref<'count' | 'name'>('count')
const onlyMulti = ref(false)
const onlyRecent = ref(false)

/** 头像加载失败的作者名集合：失败后回退到书封，避免坏图反复请求 */
const photoFailed = ref<Record<string, boolean>>({})

const FALLBACK = { title: '—', c1: 'oklch(0.62 0.16 200)', c2: 'oklch(0.48 0.13 240)' }

/** 「本周」= 最近 7 天（按名下最早一本书的入库时间判断） */
const WEEK = 7 * 24 * 3600
const weekAgo = Date.now() / 1000 - WEEK

const sortOptions = [
  { value: 'count', label: '按书量' },
  { value: 'name', label: '按姓名' },
]

function isNew(a: AuthorItem): boolean {
  return a.added_ts >= weekAgo
}

const display = computed(() => {
  let list = items.value
  if (onlyMulti.value) list = list.filter((a) => a.count >= 2)
  if (onlyRecent.value) list = list.filter(isNew)
  return [...list].sort((a, b) =>
    sortMode.value === 'name' ? a.name.localeCompare(b.name, 'zh') : b.count - a.count,
  )
})

onMounted(async () => {
  try {
    items.value = (await api.authors()).items
  } catch {
    /* 保持空列表 */
  }
  loading.value = false
})

function open(name: string): void {
  router.push(`/authors/${encodeURIComponent(name)}`)
}
</script>

<template>
  <div>
    <PageHead title="作者" :desc="`共 ${items.length} 位作者`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else>
      <div class="mb-4 flex flex-wrap items-center gap-2">
        <Segment :options="sortOptions" :model-value="sortMode" @update:model-value="(v: string) => (sortMode = v as 'count' | 'name')" />
        <button
          type="button"
          class="cursor-pointer rounded-full border px-3 py-1 text-[12px] font-medium transition-colors"
          :class="onlyMulti ? 'border-primary/40 bg-[var(--shell-accent-tint)] text-primary' : 'border-border bg-muted text-muted-foreground hover:text-foreground'"
          @click="onlyMulti = !onlyMulti"
        >
          2+ 本
        </button>
        <button
          type="button"
          class="cursor-pointer rounded-full border px-3 py-1 text-[12px] font-medium transition-colors"
          :class="onlyRecent ? 'border-primary/40 bg-[var(--shell-accent-tint)] text-primary' : 'border-border bg-muted text-muted-foreground hover:text-foreground'"
          @click="onlyRecent = !onlyRecent"
        >
          本周新增
        </button>
        <span class="ml-auto text-[11.5px] text-muted-foreground">显示 {{ display.length }} 位</span>
      </div>

      <div v-if="display.length" class="grid" :style="authorGridStyle">
        <button
          v-for="a in display"
          :key="a.name"
          type="button"
          class="group cursor-pointer text-left"
          @click="open(a.name)"
        >
          <div class="relative">
            <!-- 有真实头像时显示头像（本地缓存，零外链），否则回退到书封占位 -->
            <div
              v-if="a.has_photo && !photoFailed[a.name]"
              class="relative w-full overflow-hidden bg-muted shadow-sm transition-transform duration-200 ease-out group-hover:-translate-y-0.5"
              :class="coverShape === 'circle' ? 'aspect-square rounded-full' : 'aspect-3/4 rounded-md'"
            >
              <img
                :src="api.authorPhotoUrl(a.name)"
                :alt="a.name"
                loading="lazy"
                decoding="async"
                class="h-full w-full object-cover"
                @error="photoFailed[a.name] = true"
              >
              <div class="absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/55 to-transparent" />
            </div>
            <BookCover v-else :book="a.covers[0] ?? FALLBACK" :show-title="false" :shape="coverShape" />

            <!--
              圆形封面时两个徽章会压到圆外 —— 这是头像徽章的常规做法（像「头像上的勋章」），
              给它们加一圈背景色描边把徽章与底色分开即可；不为此挪位置，挪进去会显得过于靠里。
            -->
            <span
              class="absolute right-1.5 bottom-1.5 bg-black/55 px-1.5 py-0.5 text-[11px] font-medium text-white tabular-nums"
              :class="coverShape === 'circle' ? 'rounded-full ring-2 ring-background' : 'rounded'"
            >
              {{ a.count }} 本
            </span>
            <span
              v-if="isNew(a)"
              class="absolute top-1.5 left-1.5 bg-primary px-1.5 py-0.5 text-[10px] font-medium text-primary-foreground"
              :class="coverShape === 'circle' ? 'rounded-full ring-2 ring-background' : 'rounded'"
            >
              新
            </span>
          </div>
          <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ a.name }}</div>
          <div class="truncate text-[11.5px] text-muted-foreground">
            {{ a.series.join('、') || '—' }}
          </div>
        </button>
      </div>

      <EmptyState
        v-else
        icon="users"
        :title="onlyRecent ? '本周没有新增作者' : onlyMulti ? '没有 2 本以上的作者' : '还没有作者'"
        :desc="onlyRecent
          ? '关掉「本周新增」看看全部作者。'
          : onlyMulti ? '关掉「2+ 本」筛选看看全部作者。' : 'EPUB 元数据里带「作者」的书会自动归到这里。'"
      />
    </template>
  </div>
</template>
