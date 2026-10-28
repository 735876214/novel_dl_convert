<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type Podcast, type PodcastBookmark, type PodcastEpisode } from '@/lib/api'
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

// ---------------- 播完自动连播（第 178 期） ----------------
// 只做「本页内的上一集 / 下一集」：播放器仍是页面内的 <audio>（跨页全局播放器是另一件事）。
const autoNext = ref(localStorage.getItem('podcast-autonext') !== '0')

function setAutoNext(v: boolean): void {
  autoNext.value = v
  try {
    localStorage.setItem('podcast-autonext', v ? '1' : '0')
  } catch {
    /* 隐私模式：本次会话仍生效 */
  }
}

function playEpisode(e: PodcastEpisode): void {
  const el = audioEls[e.id]
  if (!el) return
  void el.play().catch(() => { /* 浏览器拦住就等用户点播放 */ })
}

/** 播完自动放列表里的下一条（列表按发布时间倒序，所以「下一条」= 更早的一集） */
function playNext(e: PodcastEpisode): void {
  if (!autoNext.value) return
  const i = episodes.value.findIndex((x) => x.id === e.id)
  const next = i >= 0 ? episodes.value[i + 1] : undefined
  if (next) playEpisode(next)
}

/** 同一时刻只允许一个在播（浏览器允许多个 <audio> 同时响） */
function onEpisodePlay(e: PodcastEpisode, ev: Event): void {
  for (const [id, el] of Object.entries(audioEls)) {
    if (id !== e.id && !el.paused) el.pause()
  }
  void ev
}

function onEpisodeEnded(e: PodcastEpisode, ev: Event): void {
  const el = ev.target as HTMLAudioElement
  const dur = el?.duration || e.position_sec || 0
  void api.savePodcastProgress(e.id, dur, dur)
    .then(() => { e.position_sec = dur; e.played_at = Date.now() })
    .catch(() => { /* 同上 */ })
  playNext(e)
}

async function togglePlayed(e: PodcastEpisode): Promise<void> {
  try {
    await api.markPodcastEpisodePlayed(e.id, !e.played_at)
    if (selected.value) await open(selected.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '操作失败'
  }
}

// ---------------- 单集书签（第 177 期） ----------------
// 位置到秒去重（同集同秒重复添加 = 更新标题/备注）；删除是软删除，再添加会复活。
const audioEls: Record<string, HTMLAudioElement> = {}
const bmFor = ref('')
const bmItems = ref<PodcastBookmark[]>([])

function bindAudio(eid: string, el: unknown): void {
  if (el) audioEls[eid] = el as HTMLAudioElement
  else delete audioEls[eid]
}

async function toggleBookmarks(e: PodcastEpisode): Promise<void> {
  if (bmFor.value === e.id) {
    bmFor.value = ''
    bmItems.value = []
    return
  }
  bmFor.value = e.id
  bmItems.value = []
  try {
    bmItems.value = (await api.podcastBookmarks(e.id)).items
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取书签失败'
  }
}

async function addBookmark(e: PodcastEpisode): Promise<void> {
  const el = audioEls[e.id]
  const pos = Math.floor(el?.currentTime ?? e.position_sec ?? 0)
  try {
    await api.addPodcastBookmark(e.id, { position_sec: pos, title: fmtPos(pos) })
    ui.toast('已加书签')
    if (bmFor.value === e.id) bmItems.value = (await api.podcastBookmarks(e.id)).items
    else await toggleBookmarks(e)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '加书签失败'
  }
}

async function removeBookmark(b: PodcastBookmark): Promise<void> {
  try {
    await api.deletePodcastBookmark(b.id)
    bmItems.value = bmItems.value.filter((x) => x.id !== b.id)
    ui.toast('书签已删除')
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除失败'
  }
}

function jumpBookmark(e: PodcastEpisode, b: PodcastBookmark): void {
  const el = audioEls[e.id]
  if (!el) return
  el.currentTime = b.position_sec
  void el.play().catch(() => { /* 浏览器拦住就等用户点播放 */ })
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

/** 时间点（书签 / 当前位置）：0 也要显示成 `0:00`（与时长不同，0 是一个真实位置） */
function fmtPos(sec: number): string {
  const s = Math.max(0, Math.floor(sec || 0))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
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
            <label class="ml-auto flex cursor-pointer items-center gap-1 text-[11.5px] text-muted-foreground">
              <input
                type="checkbox"
                class="h-3.5 w-3.5 cursor-pointer accent-primary"
                :checked="autoNext"
                @change="setAutoNext(($event.target as HTMLInputElement).checked)"
              >
              播完自动连播
            </label>
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
              <button
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-primary hover:underline"
                @click="toggleBookmarks(e)"
              >书签</button>
            </div>
            <p v-if="e.description" class="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-muted-foreground">
              {{ e.description }}
            </p>
            <audio
              v-if="e.audio_url"
              controls
              preload="none"
              :ref="(el) => bindAudio(e.id, el)"
              :src="audioSrc(e)"
              class="mt-1.5 h-8 w-full"
              @play="onEpisodePlay(e, $event)"
              @loadedmetadata="onEpisodeLoaded(e, $event)"
              @timeupdate="onEpisodeTime(e, $event)"
              @ended="onEpisodeEnded(e, $event)"
            />
            <div v-if="bmFor === e.id" class="mt-1.5 rounded-md border border-border bg-muted/30 p-2">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[11px] text-muted-foreground">单集书签</span>
                <Button size="sm" variant="ghost" @click="addBookmark(e)">加在当前时间</Button>
              </div>
              <ul v-if="bmItems.length" class="mt-1 space-y-0.5">
                <li v-for="b in bmItems" :key="b.id" class="flex items-center gap-2 text-[11.5px]">
                  <button
                    type="button"
                    class="shrink-0 cursor-pointer font-mono text-primary tabular-nums hover:underline"
                    @click="jumpBookmark(e, b)"
                  >{{ fmtPos(b.position_sec) }}</button>
                  <span class="min-w-0 flex-1 truncate text-muted-foreground">{{ b.title || b.note }}</span>
                  <button
                    type="button"
                    class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-destructive"
                    @click="removeBookmark(b)"
                  >删除</button>
                </li>
              </ul>
              <p v-else class="mt-1 text-[11px] text-muted-foreground">还没有书签。</p>
            </div>
          </li>
        </ul>
        </template>
      </Card>
    </template>
  </div>
</template>
