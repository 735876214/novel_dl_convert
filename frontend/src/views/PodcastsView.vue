<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type Podcast, type PodcastEpisode } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 播客（第 173 期）：订阅 / 刷新 / 浏览单集 / 直接试听。
 *
 * 为什么不是「书库」：书库在本项目里是**要被扫描的目录**，而播客是远端 RSS ——
 * 没有目录可扫。所以这里是一套独立的订阅子系统（自己的表、自己的页面），
 * 与书架 / 书目零耦合。
 *
 * 出网只在两个用户动作里发生：**订阅**与**刷新**。单集音频由浏览器直接从发布方
 * 服务器流式播放（`<audio preload="none">`），本应用不转存 —— 省磁盘，也避免
 * 「下载了一堆其实不会再听的音频」。
 */
const ui = useUiStore()

const pods = ref<Podcast[]>([])
const episodes = ref<PodcastEpisode[]>([])
const selected = ref<string>('')
const feedUrl = ref('')
const loading = ref(true)
const busy = ref('')
const error = ref('')

const selectedPodcast = computed(() => pods.value.find((p) => p.id === selected.value) || null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    pods.value = (await api.podcasts()).items
    if (selected.value && !pods.value.some((p) => p.id === selected.value)) {
      selected.value = ''
      episodes.value = []
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取订阅失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function subscribe(): Promise<void> {
  const url = feedUrl.value.trim()
  if (!url || busy.value) return
  busy.value = 'subscribe'
  error.value = ''
  try {
    const r = await api.subscribePodcast(url)
    ui.toast(r.created
      ? `已订阅「${r.podcast.title}」：新增 ${r.added} 集`
      : `已刷新「${r.podcast.title}」：新增 ${r.added} 集`)
    feedUrl.value = ''
    await load()
    await open(r.podcast.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '订阅失败'
  } finally {
    busy.value = ''
  }
}

async function refresh(p: Podcast): Promise<void> {
  if (busy.value) return
  busy.value = `refresh:${p.id}`
  error.value = ''
  try {
    const r = await api.refreshPodcast(p.id)
    ui.toast(`「${p.title}」：新增 ${r.added} 集，更新 ${r.updated} 集`)
    await load()
    if (selected.value === p.id) await open(p.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '刷新失败'
  } finally {
    busy.value = ''
  }
}

async function remove(p: Podcast): Promise<void> {
  if (busy.value) return
  busy.value = `del:${p.id}`
  try {
    await api.deletePodcast(p.id)
    ui.toast(`已移除订阅「${p.title}」`)
    if (selected.value === p.id) {
      selected.value = ''
      episodes.value = []
    }
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '移除失败'
  } finally {
    busy.value = ''
  }
}

async function open(id: string): Promise<void> {
  selected.value = id
  episodes.value = []
  try {
    episodes.value = (await api.podcastEpisodes(id)).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取单集失败'
  }
}

// ---------------- OPML 与批量刷新（第 174 期） ----------------
const opmlInput = ref<HTMLInputElement | null>(null)

async function importOpml(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || busy.value) return
  busy.value = 'opml'
  error.value = ''
  try {
    const r = await api.importPodcastsOpml(await file.text())
    ui.toast(`导入 ${r.total} 条：新增 ${r.added}、刷新 ${r.refreshed}`
      + (r.failed.length ? `、失败 ${r.failed.length}（${r.failed[0].error}）` : ''))
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导入失败'
  } finally {
    busy.value = ''
  }
}

async function exportOpml(): Promise<void> {
  if (busy.value) return
  busy.value = 'opml'
  try {
    const { opml } = await api.podcastsOpml()
    const blob = new Blob([opml], { type: 'text/x-opml;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'novelforge-podcasts.opml'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导出失败'
  } finally {
    busy.value = ''
  }
}

async function refreshAll(): Promise<void> {
  if (busy.value) return
  busy.value = 'refresh-all'
  error.value = ''
  try {
    const r = await api.refreshAllPodcasts()
    ui.toast(r.failed
      ? `刷新完成：成功 ${r.ok}、失败 ${r.failed}`
      : `刷新完成：${r.ok} 个订阅全部成功`)
    await load()
    if (selected.value) await open(selected.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '批量刷新失败'
  } finally {
    busy.value = ''
  }
}

// ---------------- 单集下载（第 175 期） ----------------
// 状态只认服务端的 `download_state`；这里只做「排队 → 轮询 → 播放本地副本」。
let pollTimer: number | undefined

// ---------------- 播放进度与筛选（第 176 期） ----------------
const epFilter = ref<'all' | 'unplayed' | 'playing' | 'played'>('all')

function epState(e: PodcastEpisode): 'unplayed' | 'playing' | 'played' {
  if (e.played_at) return 'played'
  return e.position_sec > 0 ? 'playing' : 'unplayed'
}

const episodeCounts = computed(() => {
  const c = { all: episodes.value.length, unplayed: 0, playing: 0, played: 0 }
  for (const e of episodes.value) c[epState(e)] += 1
  return c
})

const filteredEpisodes = computed(() =>
  epFilter.value === 'all' ? episodes.value
    : episodes.value.filter((e) => epState(e) === epFilter.value),
)

const EP_FILTERS: { value: 'all' | 'unplayed' | 'playing' | 'played'; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'unplayed', label: '未播' },
  { value: 'playing', label: '进行中' },
  { value: 'played', label: '已播' },
]

/** 每集最后保存进度的时间（5 秒节流；`<audio>` 的 timeupdate 一秒多次） */
const lastSaveAt: Record<string, number> = {}

function onEpisodeTime(e: PodcastEpisode, ev: Event): void {
  const el = ev.target as HTMLAudioElement
  if (!el || !Number.isFinite(el.duration) || el.duration <= 0) return
  const now = Date.now()
  if ((lastSaveAt[e.id] || 0) + 5000 > now) return
  lastSaveAt[e.id] = now
  const pos = el.currentTime
  void api.savePodcastProgress(e.id, pos, el.duration)
    .then(() => { e.position_sec = Math.max(e.position_sec, pos) })
    .catch(() => { /* 进度写失败不影响播放 */ })
}

function onEpisodeLoaded(e: PodcastEpisode, ev: Event): void {
  const el = ev.target as HTMLAudioElement
  if (!el) return
  // 续播：位置有意义且没到最后 5 秒时跳过去
  if (e.position_sec > 2 && (!el.duration || e.position_sec < el.duration - 5)) {
    el.currentTime = e.position_sec
  }
}

function onEpisodeEnded(e: PodcastEpisode, ev: Event): void {
  const el = ev.target as HTMLAudioElement
  const dur = el?.duration || e.position_sec || 0
  void api.savePodcastProgress(e.id, dur, dur)
    .then(() => { e.position_sec = dur; e.played_at = Date.now() })
    .catch(() => { /* 同上 */ })
}

async function togglePlayed(e: PodcastEpisode): Promise<void> {
  try {
    await api.markPodcastEpisodePlayed(e.id, !e.played_at)
    if (selected.value) await open(selected.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  }
}

function audioSrc(e: PodcastEpisode): string {
  return e.download_state === 'downloaded' ? api.podcastEpisodeAudioUrl(e.id) : e.audio_url
}

function startPolling(): void {
  if (pollTimer) return
  pollTimer = window.setInterval(async () => {
    if (!selected.value) {
      window.clearInterval(pollTimer)
      pollTimer = undefined
      return
    }
    try {
      episodes.value = (await api.podcastEpisodes(selected.value)).items
    } catch {
      return
    }
    if (!episodes.value.some((x) => x.download_state === 'downloading')) {
      window.clearInterval(pollTimer)
      pollTimer = undefined
    }
  }, 2000)
}

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
})

async function downloadEpisode(e: PodcastEpisode): Promise<void> {
  try {
    await api.downloadPodcastEpisode(e.id)
    e.download_state = 'downloading'
    startPolling()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '下载失败'
  }
}

async function cleanEpisode(e: PodcastEpisode): Promise<void> {
  try {
    await api.cleanPodcastEpisode(e.id)
    ui.toast('本地副本已移入回收站')
    if (selected.value) await open(selected.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '清理失败'
  }
}

async function downloadAll(): Promise<void> {
  if (!selected.value || busy.value) return
  busy.value = 'download-all'
  try {
    const r = await api.downloadAllPodcastEpisodes(selected.value)
    ui.toast(r.queued ? `已排队 ${r.queued} 集` : '没有需要下载的单集')
    await open(selected.value)
    startPolling()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批量下载失败'
  } finally {
    busy.value = ''
  }
}

function fmtDuration(sec: number): string {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor(sec % 3600 / 60)
  const s = sec % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

function fmtDate(ts: number): string {
  if (!ts) return '未知时间'
  return new Date(ts * 1000).toLocaleDateString()
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">播客</h2>
      <span class="text-[11.5px] text-muted-foreground">
        订阅 RSS 播客源；单集由浏览器直接从发布方播放，不转存
      </span>
      <div class="ml-auto flex gap-1">
        <input ref="opmlInput" type="file" accept=".opml,.xml,text/xml" class="hidden" aria-hidden="true" @change="importOpml">
        <Button size="sm" variant="ghost" :disabled="!!busy" @click="opmlInput?.click()">导入 OPML</Button>
        <Button size="sm" variant="ghost" :disabled="!!busy || !pods.length" @click="exportOpml">导出 OPML</Button>
        <Button size="sm" variant="ghost" :disabled="!!busy || !pods.length" @click="refreshAll">
          {{ busy === 'refresh-all' ? '刷新中…' : '全部刷新' }}
        </Button>
      </div>
    </div>

    <Card>
      <div class="flex flex-wrap items-end gap-2">
        <label class="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">RSS 地址</span>
          <input
            v-model="feedUrl"
            type="url"
            aria-label="RSS 地址"
            placeholder="https://example.com/feed.xml"
            class="h-8 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @keyup.enter="subscribe"
          >
        </label>
        <Button size="sm" variant="primary" :disabled="!!busy || !feedUrl.trim()" @click="subscribe">
          {{ busy === 'subscribe' ? '订阅中…' : '订阅' }}
        </Button>
      </div>
      <p class="mt-1.5 text-[11px] text-muted-foreground">
        只支持 RSS 2.0（含 iTunes 扩展）；Atom 源会如实拒绝。同一地址重复订阅 = 刷新。
      </p>
      <p v-if="error" class="mt-1.5 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <div v-if="loading" class="py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

    <EmptyState
      v-else-if="!pods.length"
      icon="volume"
      title="还没有订阅"
      desc="把播客的 RSS 地址填到上面，就能在这里浏览单集并试听。"
    />

    <template v-else>
      <Card padding="none">
        <ul class="divide-y divide-border">
          <li
            v-for="p in pods"
            :key="p.id"
            class="flex flex-wrap items-center gap-3 px-4 py-3"
            :class="p.id === selected ? 'bg-muted/40' : ''"
          >
            <img
              v-if="p.artwork_url"
              :src="p.artwork_url"
              alt=""
              referrerpolicy="no-referrer"
              class="h-12 w-12 shrink-0 rounded-md border border-border object-cover"
            >
            <div v-else class="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
              <Icon name="volume" class="h-4 w-4 text-muted-foreground" />
            </div>
            <div class="min-w-0 flex-1">
              <button type="button" class="cursor-pointer truncate text-left text-[13px] font-medium text-foreground hover:text-primary" @click="open(p.id)">
                {{ p.title }}
              </button>
              <div class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                {{ p.author || '未知作者' }}
                <span v-if="p.categories.length"> · {{ p.categories.join('、') }}</span>
                <span v-if="p.last_fetched_at"> · 上次刷新 {{ fmtDate(p.last_fetched_at) }}</span>
                <span
                  v-if="p.fail_count"
                  class="text-destructive"
                  :title="p.last_error"
                > · 失败 {{ p.fail_count }} 次</span>
              </div>
            </div>
            <div class="flex shrink-0 gap-1">
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="open(p.id)">
                {{ p.id === selected ? '收起' : '单集' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="refresh(p)">
                {{ busy === `refresh:${p.id}` ? '刷新中…' : '刷新' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="remove(p)">移除</Button>
            </div>
          </li>
        </ul>
      </Card>

      <Card v-if="selectedPodcast">
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <h3 class="text-[13px] font-semibold text-foreground">
            {{ selectedPodcast.title }} · 单集
            <span class="ml-1 text-[11px] font-normal text-muted-foreground">共 {{ episodes.length }} 集</span>
          </h3>
          <Button size="sm" variant="ghost" class="ml-auto" :disabled="!!busy || !episodes.length" @click="downloadAll">
            {{ busy === 'download-all' ? '排队中…' : '下载全部未下载' }}
          </Button>
        </div>
        <EmptyState
          v-if="!episodes.length"
          icon="volume"
          title="还没有单集"
          desc="点上面的「刷新」去发布方那里取最新一期。"
        />
        <template v-else>
          <div class="mb-2 flex flex-wrap items-center gap-1">
            <button
              v-for="f in EP_FILTERS"
              :key="f.value"
              type="button"
              class="cursor-pointer rounded-full px-2.5 py-0.5 text-[11.5px] font-medium transition-colors"
              :class="epFilter === f.value ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'"
              @click="epFilter = f.value"
            >
              {{ f.label }} <span class="tabular-nums opacity-70">{{ episodeCounts[f.value] }}</span>
            </button>
          </div>
        <ul class="divide-y divide-border">
          <li v-for="e in filteredEpisodes" :key="e.id" class="py-2.5">
            <div class="flex flex-wrap items-baseline gap-2">
              <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">{{ e.title }}</span>
              <span
                v-if="e.played_at"
                class="shrink-0 rounded bg-primary/10 px-1 text-[10px] text-primary"
              >已播</span>
              <span
                v-else-if="e.position_sec > 0"
                class="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground"
              >进行中 {{ Math.round((e.position_sec / Math.max(1, e.duration_sec || e.position_sec)) * 100) }}%</span>
              <span
                v-if="e.download_state === 'downloading'"
                class="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground"
              >下载中</span>
              <span
                v-else-if="e.download_state === 'downloaded'"
                class="shrink-0 rounded bg-emerald-500/15 px-1 text-[10px] text-emerald-600 dark:text-emerald-400"
              >已下载</span>
              <span
                v-else-if="e.download_state === 'failed'"
                class="shrink-0 rounded bg-destructive/14 px-1 text-[10px] text-destructive"
                :title="e.download_error"
              >下载失败</span>
              <span class="shrink-0 text-[11px] text-muted-foreground">{{ fmtDate(e.published_at) }}</span>
              <span v-if="e.duration_sec" class="shrink-0 text-[11px] text-muted-foreground tabular-nums">
                {{ fmtDuration(e.duration_sec) }}
              </span>
              <button
                v-if="e.download_state !== 'downloaded' && e.download_state !== 'downloading' && e.audio_url"
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-primary hover:underline"
                @click="downloadEpisode(e)"
              >下载</button>
              <button
                v-if="e.download_state === 'downloaded'"
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-destructive"
                @click="cleanEpisode(e)"
              >清理</button>
              <button
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-primary"
                @click="togglePlayed(e)"
              >{{ e.played_at ? '标未播' : '标已播' }}</button>
            </div>
            <p v-if="e.description" class="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-muted-foreground">
              {{ e.description }}
            </p>
            <audio
              v-if="e.audio_url"
              controls
              preload="none"
              :src="audioSrc(e)"
              class="mt-1.5 h-8 w-full"
              @loadedmetadata="onEpisodeLoaded(e, $event)"
              @timeupdate="onEpisodeTime(e, $event)"
              @ended="onEpisodeEnded(e, $event)"
            />
          </li>
        </ul>
        </template>
      </Card>
    </template>
  </div>
</template>
