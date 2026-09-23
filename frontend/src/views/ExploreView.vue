<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type SearchHit } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

/**
 * 探索发现：跨全部已启用书源聚合检索，结果可预览与下载。
 * 接真实 POST /api/search、GET /api/preview、POST /api/download + GET /api/tasks/{tid} 轮询。
 *
 * 竞态防护：每次搜索用新的 AbortController，并在发起前 abort 上一次。
 */
const ui = useUiStore()
const tasks = useTasksStore()
const library = useLibraryStore()

const keyword = ref('')
const searching = ref(false)
const searched = ref(false)
const hits = ref<SearchHit[]>([])
const errors = ref<string[]>([])

const previewOpen = ref(false)
const previewTitle = ref('')
const previewText = ref('')
const previewLoading = ref(false)

let inflight: AbortController | null = null

const HOT_WORDS = ['三体', '诡秘之主', '长安的荔枝', '凡人修仙传', '球状闪电']

const hasResults = computed(() => hits.value.length > 0)

/** Esc 关闭预览弹窗（无障碍：弹窗应可键盘关闭） */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && previewOpen.value) previewOpen.value = false
}
onMounted(() => window.addEventListener('keydown', onKeydown))

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  inflight?.abort()
})

function runSearch(word?: string): void {
  const q = (word ?? keyword.value).trim()
  if (!q) {
    ui.toast('请输入书名')
    return
  }
  keyword.value = q

  inflight?.abort()
  inflight = new AbortController()

  searching.value = true
  api
    .search(q, inflight.signal)
    .then((r) => {
      hits.value = r.results ?? r.items ?? []
      errors.value = (r.errors ?? []).map((e) => String(e))
      searched.value = true
    })
    .catch((e: Error) => {
      if (e.name === 'AbortError') return
      ui.toast(e.message)
    })
    .finally(() => {
      searching.value = false
    })
}

function openPreview(hit: SearchHit): void {
  previewOpen.value = true
  previewTitle.value = hit.title
  previewText.value = ''
  previewLoading.value = true
  api
    .preview(hit.source, hit.url)
    .then((data) => {
      const d = data as Record<string, unknown>
      const chapters = Array.isArray(d.chapters) ? d.chapters.length : undefined
      previewText.value = [
        d.author ? `作者：${d.author}` : '',
        d.intro ? `\n${String(d.intro)}` : '',
        chapters !== undefined ? `\n\n共 ${chapters} 章` : '',
      ]
        .filter(Boolean)
        .join('\n')
    })
    .catch((e: Error) => {
      previewText.value = `预览失败：${e.message}`
    })
    .finally(() => {
      previewLoading.value = false
    })
}

/** 发起下载：交给后端，然后让任务 store 从服务端刷新真实状态 */
function startDownload(hit: SearchHit): void {
  // 0 库时**提前拦下**（第 38 期）：后端此时会收下任务再在后台失败
  //（`_run_download` 里 `no_library_reason()` ⇒ 任务标 failed），用户看到的是
  //「已加入下载队列」，失败却要跑到任务中心才发现 —— 一次注定失败的往返没必要发。
  if (library.hasNoLibraries) {
    ui.toast('还没有书库：先到「工具 → 书库管理」新建一个书库，下载才有地方落')
    return
  }
  api
    .download({ ...hit })
    .then(() => {
      ui.toast(`已加入下载队列：${hit.title}`)
      // 任务状态统一由 store 从 /api/tasks 拉取并按需轮询，本页不再维护第二套轮询。
      // （旧实现在这里自建轮询，且把失败状态判断成 'error'，而后端写的是 'failed'，
      //   于是失败任务会永远停在「下载中」并无限轮询。）
      void tasks.track()
    })
    .catch((e: Error) => ui.toast(e.message))
}
</script>

<template>
  <div>
    <PageHead
      title="探索发现"
      :desc="
        library.hasNoLibraries
          ? '跨全部已启用书源聚合检索 —— 但还没有书库，下载前请先到「工具 → 书库管理」新建一个'
          : '跨全部已启用书源聚合检索，选中结果可直接下载'
      "
    />

    <Card class="mb-4">
      <div class="flex items-center gap-2">
        <div class="relative min-w-0 flex-1">
          <Icon name="search" class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="keyword"
            type="text"
            placeholder="输入书名，例如「三体」"
            aria-label="搜索书名"
            class="h-9 w-full rounded-md border border-border bg-muted pr-3 pl-9 text-[13px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
            @keydown.enter="runSearch()"
          >
        </div>
        <Button variant="primary" size="md" :disabled="searching" @click="runSearch()">
          {{ searching ? '检索中…' : '检索' }}
        </Button>
      </div>

      <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
        <span class="text-[11.5px] text-muted-foreground">热词</span>
        <button
          v-for="w in HOT_WORDS"
          :key="w"
          type="button"
          class="cursor-pointer rounded-full bg-muted px-2.5 py-0.5 text-[11.5px] text-muted-foreground transition-colors hover:bg-[var(--shell-accent-tint)] hover:text-primary"
          @click="runSearch(w)"
        >
          {{ w }}
        </button>
      </div>
    </Card>

    <div v-if="errors.length" class="mb-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
      <p class="text-[11.5px] text-warning">部分书源检索失败：{{ errors.join('；') }}</p>
    </div>

    <p v-if="!searching && hasResults" class="mb-2 text-[11.5px] text-muted-foreground">
      共 {{ hits.length }} 条结果
    </p>

    <Card v-if="searching" class="py-10 text-center text-[12.5px] text-muted-foreground">
      正在并发检索各书源…
    </Card>

    <Card v-else-if="hasResults" padding="none">
      <div
        v-for="(h, i) in hits"
        :key="`${h.source}-${i}`"
        class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] font-medium text-foreground">{{ h.title }}</div>
          <div class="mt-0.5 flex items-center gap-2">
            <Badge tone="accent">{{ h.source }}</Badge>
            <span v-if="h.author" class="truncate text-[11.5px] text-muted-foreground">{{ h.author }}</span>
          </div>
        </div>
        <Button size="sm" @click="openPreview(h)">预览</Button>
        <Button size="sm" variant="primary" @click="startDownload(h)">下载</Button>
      </div>
    </Card>

    <EmptyState
      v-else-if="searched"
      icon="search"
      title="没有找到结果"
      desc="换个书名再试，或到「书源管理」确认书源是否已启用。"
    />

    <EmptyState
      v-else
      icon="globe"
      title="开始检索"
      desc="输入书名后会并发查询全部已启用书源，结果按来源分组展示。"
    />

    <!-- 预览弹窗 -->
    <div
      v-if="previewOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="explore-preview-title"
      @click.self="previewOpen = false"
    >
      <div class="w-[min(32rem,92vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <div class="mb-3 flex items-start gap-2">
          <h3 id="explore-preview-title" class="min-w-0 flex-1 font-serif text-[16px] font-semibold text-foreground">{{ previewTitle }}</h3>
          <button
            type="button"
            class="grid h-6 w-6 cursor-pointer place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="关闭预览"
            @click="previewOpen = false"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" class="h-3.5 w-3.5">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div class="max-h-[50vh] overflow-y-auto text-[12.5px] leading-relaxed whitespace-pre-line text-muted-foreground">
          {{ previewLoading ? '加载中…' : previewText }}
        </div>
      </div>
    </div>
  </div>
</template>
