<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type SearchHit } from '@/lib/api'
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

const keyword = ref('')
const searching = ref(false)
const searched = ref(false)
const hits = ref<SearchHit[]>([])
const errors = ref<string[]>([])

const previewOpen = ref(false)
const previewTitle = ref('')
const previewText = ref('')
const previewLoading = ref(false)

/** 下载任务轮询句柄：组件卸载时必须清掉 */
const pollers = new Map<string, ReturnType<typeof setInterval>>()
let inflight: AbortController | null = null

const HOT_WORDS = ['三体', '诡秘之主', '长安的荔枝', '凡人修仙传', '球状闪电']

const hasResults = computed(() => hits.value.length > 0)

onUnmounted(() => {
  inflight?.abort()
  pollers.forEach((t) => clearInterval(t))
  pollers.clear()
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

/** 发起下载并轮询后端任务状态，进度回写任务 store */
function startDownload(hit: SearchHit): void {
  api
    .download({ ...hit })
    .then((r) => {
      const tid = r.task_id
      tasks.addTask({
        id: tid,
        book: hit.title,
        type: 'download',
        detail: `${hit.source} · 排队中`,
        progress: 0,
        status: 'queued',
      })
      ui.toast(`已加入下载队列：${hit.title}`)

      const timer = setInterval(() => {
        api
          .task(tid)
          .then((state) => {
            if (state.status === 'done') {
              clearInterval(timer)
              pollers.delete(tid)
              tasks.patchTask(tid, { status: 'done', progress: 100, detail: `${hit.source} · 已完成` })
              ui.toast(`${hit.title} 下载完成`)
              return
            }
            if (state.status === 'error') {
              clearInterval(timer)
              pollers.delete(tid)
              tasks.patchTask(tid, {
                status: 'failed',
                progress: 100,
                error: state.error ?? '下载失败',
              })
              ui.toast(`${hit.title} 下载失败`)
              return
            }
            tasks.patchTask(tid, { status: 'running', detail: `${hit.source} · 下载中` })
          })
          .catch(() => {
            // 轮询失败不中断，等下一次；连续失败由后端恢复后自然继续
          })
      }, 1500)

      pollers.set(tid, timer)
    })
    .catch((e: Error) => ui.toast(e.message))
}
</script>

<template>
  <div>
    <PageHead title="探索发现" desc="跨全部已启用书源聚合检索，选中结果可直接下载" />

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
    <div v-if="previewOpen" class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4" @click.self="previewOpen = false">
      <div class="w-[min(32rem,92vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <div class="mb-3 flex items-start gap-2">
          <h3 class="min-w-0 flex-1 font-serif text-[16px] font-semibold text-foreground">{{ previewTitle }}</h3>
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
