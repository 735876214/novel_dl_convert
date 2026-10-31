<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type Podcast, type PodcastBookmark, type PodcastCollection, type PodcastContinueItem, type PodcastDirectoryItem, type PodcastEpisode, type PodcastEpisodeLite, type PodcastPlaylist } from '@/lib/api'
import {
  BUILTIN_PLAYLISTS,
  EPISODE_FIELD_LABELS,
  EPISODE_FIELD_OPS,
  EPISODE_OP_LABELS,
  episodeRuleText,
  evaluateEpisodeScope,
  type EpisodeRule,
  type EpisodeScopeField,
  type EpisodeScopeOp,
} from '@/lib/episodeScope'
import { usePodcastQueueStore } from '@/stores/podcastQueue'
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
const queue = usePodcastQueueStore()

const pods = ref<Podcast[]>([])
const episodes = ref<PodcastEpisode[]>([])
const selected = ref<string>('')
const feedUrl = ref('')
const loading = ref(true)
const busy = ref('')
const error = ref('')

const selectedPodcast = computed(() => pods.value.find((p) => p.id === selected.value) || null)
/** 播客版「继续收听」（第 183 期）：跨订阅的「听过未完播」 */
const contItems = ref<PodcastContinueItem[]>([])
/** 单集搜索词（第 183 期）：只过滤当前订阅的单集列表 */
const q = ref('')

// ---------------- 播客合集（第 185 期） ----------------
// 只装订阅（节目），不装单集 / 不装书。成员按未软删的订阅过滤：移除订阅后计数归零，
// 重订阅同一 feed 复活原行，合集里的位置也跟着回来。
const colls = ref<PodcastCollection[]>([])
const activeColl = ref<number | null>(null)
const collName = ref('')
const collBusy = ref(false)

const activeCollection = computed(
  () => colls.value.find((c) => c.id === activeColl.value) || null,
)
const visiblePods = computed(() => {
  const c = activeCollection.value
  if (!c) return pods.value
  const ids = new Set(c.podcast_ids)
  return pods.value.filter((p) => ids.has(p.id))
})

async function createColl(): Promise<void> {
  const name = collName.value.trim()
  if (!name || collBusy.value) return
  collBusy.value = true
  error.value = ''
  try {
    const c = await api.createPodcastCollection(name)
    colls.value = [c, ...colls.value]
    activeColl.value = c.id
    collName.value = c.name
    ui.toast(`已新建合集「${c.name}」`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '新建合集失败'
  } finally {
    collBusy.value = false
  }
}

async function renameColl(): Promise<void> {
  const c = activeCollection.value
  const name = collName.value.trim()
  if (!c || !name || collBusy.value) return
  collBusy.value = true
  error.value = ''
  try {
    const out = await api.renamePodcastCollection(c.id, name)
    colls.value = colls.value.map((x) => (x.id === out.id ? out : x))
    ui.toast(`合集已改名为「${out.name}」`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重命名失败'
  } finally {
    collBusy.value = false
  }
}

async function deleteColl(): Promise<void> {
  const c = activeCollection.value
  if (!c || collBusy.value) return
  collBusy.value = true
  error.value = ''
  try {
    await api.deletePodcastCollection(c.id)
    colls.value = colls.value.filter((x) => x.id !== c.id)
    activeColl.value = null
    collName.value = ''
    ui.toast(`已删除合集「${c.name}」`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除合集失败'
  } finally {
    collBusy.value = false
  }
}

function selectColl(c: PodcastCollection | null): void {
  activeColl.value = c ? c.id : null
  collName.value = c ? c.name : ''
}

function replaceColl(out: PodcastCollection): void {
  colls.value = colls.value.map((x) => (x.id === out.id ? out : x))
}

async function addToColl(p: Podcast, ev: Event): Promise<void> {
  const sel = ev.target as HTMLSelectElement
  const cid = Number(sel.value)
  sel.value = ''
  if (!cid || collBusy.value) return
  collBusy.value = true
  error.value = ''
  try {
    replaceColl(await api.addPodcastToCollection(cid, p.id))
    ui.toast(`已把「${p.title}」加入合集`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加入合集失败'
  } finally {
    collBusy.value = false
  }
}

async function removeFromActive(p: Podcast): Promise<void> {
  const c = activeCollection.value
  if (!c || collBusy.value) return
  collBusy.value = true
  error.value = ''
  try {
    replaceColl(await api.removePodcastFromCollection(c.id, p.id))
    ui.toast(`已把「${p.title}」移出合集`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '移出合集失败'
  } finally {
    collBusy.value = false
  }
}

// ---------------- 智能播放列表（第 186 期） ----------------
// 规则存服务端（podcast_playlists），求值在 lib/episodeScope.ts；取源是全部订阅的单集 lite。
// 内置四条（快速听 / 继续收听 / 已下载 / 本周更新）不落库，与保存的规则走同一条求值路径。
const allEps = ref<PodcastEpisodeLite[]>([])
let allEpsLoaded = false
const playlists = ref<PodcastPlaylist[]>([])
const activePl = ref<number | null>(null)
const activeBuiltin = ref('')
const plRows = ref<{ id: string; title: string; podcast_id: string; podcast_title: string; duration_sec: number; status: string }[]>([])
const plName = ref('')
const plMatch = ref<'all' | 'any'>('all')
const draftRules = ref<EpisodeRule[]>([])
const ruleField = ref<EpisodeScopeField>('status')
const ruleOp = ref<EpisodeScopeOp>('equals')
const ruleValue = ref('')
const plBusy = ref(false)
const plMsg = ref('')

const ruleOps = computed(() => EPISODE_FIELD_OPS[ruleField.value])
type BuiltinPl = (typeof BUILTIN_PLAYLISTS)[number]

function setRuleField(): void {
  ruleOp.value = EPISODE_FIELD_OPS[ruleField.value][0]
}

function resetDraft(): void {
  draftRules.value = []
  ruleValue.value = ''
  plMsg.value = ''
}

function addDraftRule(): void {
  const value = ruleValue.value.trim()
  if (!value) {
    plMsg.value = '先填规则值'
    return
  }
  draftRules.value = [...draftRules.value, { field: ruleField.value, op: ruleOp.value, value }]
  ruleValue.value = ''
  plMsg.value = ''
}

function removeDraftRule(i: number): void {
  draftRules.value = draftRules.value.filter((_, idx) => idx !== i)
}

async function ensureAllEps(): Promise<boolean> {
  if (allEpsLoaded) return true
  try {
    allEps.value = (await api.podcastEpisodesAll()).items
    allEpsLoaded = true
    return true
  } catch (e) {
    plMsg.value = e instanceof Error ? e.message : '读取单集失败'
    return false
  }
}

function rowsOf(eps: PodcastEpisodeLite[]) {
  return eps.map((e) => ({
    id: e.id,
    title: e.title,
    podcast_id: e.podcast_id,
    podcast_title: e.podcast_title,
    duration_sec: e.duration_sec,
    status: Number(e.played_at ?? 0) > 0 ? '已播' : Number(e.position_sec ?? 0) > 0 ? '进行中' : '未播',
  }))
}

async function applyBuiltin(b: BuiltinPl): Promise<void> {
  activePl.value = null
  activeBuiltin.value = b.key
  plMsg.value = ''
  if (!(await ensureAllEps())) return
  plRows.value = rowsOf(evaluateEpisodeScope(allEps.value, b.rules, b.match))
}

async function applySaved(p: PodcastPlaylist): Promise<void> {
  activePl.value = p.id
  activeBuiltin.value = ''
  plMsg.value = ''
  if (p.kind === 'queue') {
    plRows.value = p.items.map((it) => ({
      id: it.episode_id,
      title: it.title,
      podcast_id: it.podcast_id,
      podcast_title: it.podcast_title,
      duration_sec: 0,
      status: '',
    }))
    return
  }
  if (!(await ensureAllEps())) return
  plRows.value = rowsOf(evaluateEpisodeScope(allEps.value, p.rules, p.match))
}

async function savePlaylist(): Promise<void> {
  const name = plName.value.trim()
  if (!name) {
    plMsg.value = '先填播放列表名'
    return
  }
  if (!draftRules.value.length) {
    plMsg.value = '至少加一条规则（空规则会命中全部单集）'
    return
  }
  plBusy.value = true
  plMsg.value = ''
  try {
    const p = await api.createPodcastPlaylist({
      name, kind: 'rules', match: plMatch.value, rules: draftRules.value,
    })
    playlists.value = [p, ...playlists.value]
    resetDraft()
    await applySaved(p)
    ui.toast(`已保存播放列表「${p.name}」`)
  } catch (e) {
    plMsg.value = e instanceof Error ? e.message : '保存播放列表失败'
  } finally {
    plBusy.value = false
  }
}

async function saveFromQueue(): Promise<void> {
  const name = plName.value.trim()
  if (!name) {
    plMsg.value = '先填播放列表名'
    return
  }
  if (!queue.items.length) {
    plMsg.value = '播放队列是空的'
    return
  }
  plBusy.value = true
  plMsg.value = ''
  try {
    const p = await api.createPodcastPlaylist({
      name, kind: 'queue',
      items: queue.items.map((it) => ({
        episode_id: it.episodeId,
        title: it.title,
        podcast_id: it.podcastId,
        podcast_title: it.podcastTitle,
      })),
    })
    playlists.value = [p, ...playlists.value]
    resetDraft()
    await applySaved(p)
    ui.toast(`已把队列保存为「${p.name}」`)
  } catch (e) {
    plMsg.value = e instanceof Error ? e.message : '保存队列失败'
  } finally {
    plBusy.value = false
  }
}

async function deletePlaylist(): Promise<void> {
  const p = playlists.value.find((x) => x.id === activePl.value)
  if (!p || plBusy.value) return
  plBusy.value = true
  try {
    await api.deletePodcastPlaylist(p.id)
    playlists.value = playlists.value.filter((x) => x.id !== p.id)
    activePl.value = null
    plRows.value = []
    ui.toast(`已删除播放列表「${p.name}」`)
  } catch (e) {
    plMsg.value = e instanceof Error ? e.message : '删除播放列表失败'
  } finally {
    plBusy.value = false
  }
}

const plTitle = computed(() => {
  if (activeBuiltin.value) {
    return BUILTIN_PLAYLISTS.find((b) => b.key === activeBuiltin.value)?.name || ''
  }
  return playlists.value.find((p) => p.id === activePl.value)?.name || ''
})

async function playPlRow(row: { id: string; podcast_id: string }): Promise<void> {
  await playQueueItem({ episodeId: row.id, podcastId: row.podcast_id })
}

function addAllPlToQueue(): void {
  let added = 0
  for (const row of plRows.value) {
    if (queue.enqueue({
      episodeId: row.id,
      podcastId: row.podcast_id,
      title: row.title,
      podcastTitle: row.podcast_title,
    })) added += 1
  }
  ui.toast(added ? `已加入队列 ${added} 集` : '这些单集已在队列里')
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    pods.value = (await api.podcasts()).items
    contItems.value = (await api.podcastContinue(20).catch(() => ({ items: [] }))).items
    colls.value = (await api.podcastCollections().catch(() => ({ items: [] }))).items
    playlists.value = (await api.podcastPlaylists().catch(() => ({ items: [] }))).items
    allEpsLoaded = false
    if (activeColl.value && !colls.value.some((c) => c.id === activeColl.value)) {
      activeColl.value = null
      collName.value = ''
    }
    if (activePl.value && !playlists.value.some((p) => p.id === activePl.value)) {
      activePl.value = null
      plRows.value = []
    }
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

// ---------------- 目录搜索（第 187 期） ----------------
// 只有点「搜索目录」才出网；开关关闭 / 网络失败都在 dirMsg 里如实说明，手动填 RSS 照旧可用。
const dirTerm = ref('')
const dirResults = ref<PodcastDirectoryItem[]>([])
const dirBusy = ref(false)
const dirMsg = ref('')

async function searchDir(): Promise<void> {
  const q = dirTerm.value.trim()
  if (!q || dirBusy.value) return
  dirBusy.value = true
  dirMsg.value = ''
  try {
    dirResults.value = (await api.searchPodcastDirectory(q)).items
    if (!dirResults.value.length) dirMsg.value = '目录里没有找到带 RSS 地址的节目'
  } catch (e) {
    dirResults.value = []
    dirMsg.value = e instanceof Error ? e.message : '目录搜索失败'
  } finally {
    dirBusy.value = false
  }
}

async function subscribeFromDir(it: PodcastDirectoryItem): Promise<void> {
  feedUrl.value = it.feed_url
  await subscribe()
  dirResults.value = []
  dirTerm.value = ''
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

// ---------------- 官方转录（第 182 期） ----------------
// 只读 feed 给的转录文件（按需抓取并缓存）；没有就如实说明「不做 ASR」。
const trFor = ref('')
const trText = ref('')
const trReason = ref('')
const trBusy = ref(false)

async function toggleTranscript(e: PodcastEpisode): Promise<void> {
  if (trFor.value === e.id) {
    trFor.value = ''
    return
  }
  trFor.value = e.id
  trText.value = ''
  trReason.value = ''
  trBusy.value = true
  try {
    const r = await api.podcastTranscript(e.id)
    trText.value = r.text || ''
    trReason.value = r.available ? '' : (r.reason || '没有可用的转录')
  } catch (err) {
    trReason.value = err instanceof Error ? err.message : '读取转录失败'
  } finally {
    trBusy.value = false
  }
}

// ---------------- 自动策略（第 181 期） ----------------
// 自动下载「最新 N 集」在刷新之后执行；听完清理只清本地副本（回收站）。
const autoKeep = ref(0)
const autoClean = ref(false)
const autoBusy = ref(false)

function syncAuto(): void {
  const p = selectedPodcast.value
  autoKeep.value = p?.auto_keep ?? 0
  autoClean.value = p?.auto_clean ?? false
}

async function saveAuto(): Promise<void> {
  const p = selectedPodcast.value
  if (!p || autoBusy.value) return
  autoBusy.value = true
  try {
    const keep = Math.max(0, Math.min(50, Math.round(Number(autoKeep.value) || 0)))
    const r = await api.setPodcastAuto(p.id, { auto_keep: keep, auto_clean: autoClean.value })
    autoKeep.value = r.auto_keep
    autoClean.value = r.auto_clean
    ui.toast(keep ? `已开启：自动下载最新 ${keep} 集` : '已关闭自动下载')
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存失败'
  } finally {
    autoBusy.value = false
  }
}

async function open(id: string): Promise<void> {
  selected.value = id
  syncAuto()
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

const filteredEpisodes = computed(() => {
  const term = q.value.trim().toLowerCase()
  return episodes.value.filter((e) => {
    if (epFilter.value !== 'all' && epState(e) !== epFilter.value) return false
    if (!term) return true
    return `${e.title} ${e.description}`.toLowerCase().includes(term)
  })
})

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

// ---------------- 播放队列（第 180 期） ----------------
// 队列存快照（id + 标题 + 订阅），播放时回订阅里按 id 取当前那一集；
// 播完优先取队首，队列空才走「播完自动连播」的列表顺序。
async function playContinue(it: PodcastContinueItem): Promise<void> {
  if (it.podcast_id !== selected.value) await open(it.podcast_id)
  const ep = episodes.value.find((x) => x.id === it.id)
  if (!ep) {
    ui.toast('这一集不在当前列表里（可能已被移除）')
    return
  }
  const el = audioEls[ep.id]
  if (el) {
    el.currentTime = it.position_sec
    void el.play().catch(() => { /* 浏览器拦住就等用户点播放 */ })
  }
}

function toggleQueue(e: PodcastEpisode): void {
  if (queue.has(e.id)) {
    queue.remove(e.id)
    ui.toast('已移出播放队列')
    return
  }
  const pod = selectedPodcast.value
  const ok = queue.enqueue({
    episodeId: e.id,
    podcastId: e.podcast_id,
    title: e.title,
    podcastTitle: pod?.title || '',
  })
  ui.toast(ok ? '已加入播放队列' : '队列已满或已存在')
}

async function playQueueItem(it: { episodeId: string; podcastId: string }): Promise<void> {
  if (it.podcastId !== selected.value) {
    await open(it.podcastId)
  }
  const ep = episodes.value.find((x) => x.id === it.episodeId)
  if (ep) playEpisode(ep)
  else ui.toast('这一集已不在订阅里')
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
  const nextQ = queue.shift()
  if (nextQ) {
    void playQueueItem(nextQ)
    return
  }
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

      <!-- 目录搜索（第 187 期）：后端代取；开关关闭 / 失败都如实说明，不挡手动填地址 -->
      <div class="mt-2 flex flex-wrap items-end gap-2">
        <label class="flex min-w-[14rem] flex-1 flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">搜索播客目录</span>
          <input
            v-model="dirTerm"
            type="search"
            aria-label="搜索播客目录"
            placeholder="按节目名搜索（iTunes）"
            class="h-8 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @keyup.enter="searchDir"
          >
        </label>
        <Button size="sm" variant="ghost" :disabled="dirBusy || !dirTerm.trim()" @click="searchDir">
          {{ dirBusy ? '搜索中…' : '搜索目录' }}
        </Button>
      </div>
      <p v-if="dirMsg" class="mt-1.5 text-[11.5px] text-destructive">{{ dirMsg }}</p>
      <ul v-if="dirResults.length" class="mt-1.5 divide-y divide-border rounded-md border border-border">
        <li v-for="it in dirResults" :key="it.feed_url" class="flex flex-wrap items-center gap-2 px-2 py-1.5 text-[11.5px]">
          <img
            v-if="it.artwork_url"
            :src="it.artwork_url"
            alt=""
            referrerpolicy="no-referrer"
            class="h-8 w-8 shrink-0 rounded border border-border object-cover"
          >
          <div class="min-w-0 flex-1">
            <div class="truncate font-medium text-foreground">{{ it.title || it.feed_url }}</div>
            <div class="truncate text-[11px] text-muted-foreground">
              {{ it.author || '未知作者' }}<template v-if="it.episode_count"> · {{ it.episode_count }} 集</template>
            </div>
          </div>
          <Button size="sm" variant="primary" :disabled="!!busy" @click="subscribeFromDir(it)">订阅</Button>
        </li>
      </ul>
      <p v-if="error" class="mt-1.5 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <!-- 播客合集（第 185 期）：只装订阅（节目），计数按未软删的订阅算 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[11.5px] font-medium text-muted-foreground">合集</span>
        <button
          v-for="c in colls"
          :key="c.id"
          type="button"
          class="cursor-pointer rounded-full border px-2 py-0.5 text-[11.5px]"
          :class="c.id === activeColl
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-border text-muted-foreground hover:text-foreground'"
          @click="selectColl(c)"
        >{{ c.name }}（{{ c.count }}）</button>
        <button
          v-if="activeCollection"
          type="button"
          class="cursor-pointer rounded-full border border-border px-2 py-0.5 text-[11.5px] text-muted-foreground hover:text-foreground"
          @click="selectColl(null)"
        >全部订阅</button>
        <div class="ml-auto flex flex-wrap items-center gap-1">
          <input
            v-model="collName"
            aria-label="合集名"
            placeholder="合集名"
            class="h-7 w-32 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
            :disabled="collBusy"
            @keyup.enter="activeCollection ? renameColl() : createColl()"
          >
          <Button
            size="sm"
            variant="ghost"
            :disabled="collBusy || !collName.trim()"
            @click="activeCollection ? renameColl() : createColl()"
          >{{ activeCollection ? '重命名合集' : '新建合集' }}</Button>
          <Button v-if="activeCollection" size="sm" variant="ghost" :disabled="collBusy" @click="deleteColl">
            删除合集
          </Button>
        </div>
      </div>
      <p class="mt-1.5 text-[11px] text-muted-foreground">
        合集只装订阅（节目）；移除订阅后计数归零，重订阅同一 feed 会恢复合集里的位置。
      </p>
    </Card>

    <!-- 智能播放列表（第 186 期）：规则存服务端，求值在前端 lib/episodeScope.ts -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[11.5px] font-medium text-muted-foreground">智能播放列表</span>
        <button
          v-for="b in BUILTIN_PLAYLISTS"
          :key="b.key"
          type="button"
          class="cursor-pointer rounded-full border px-2 py-0.5 text-[11.5px]"
          :class="activeBuiltin === b.key
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-border text-muted-foreground hover:text-foreground'"
          @click="applyBuiltin(b)"
        >{{ b.name }}</button>
        <button
          v-for="p in playlists"
          :key="p.id"
          type="button"
          class="cursor-pointer rounded-full border px-2 py-0.5 text-[11.5px]"
          :class="p.id === activePl
            ? 'border-primary bg-primary/10 text-primary'
            : 'border-border text-muted-foreground hover:text-foreground'"
          @click="applySaved(p)"
        >{{ p.name }}（{{ p.kind === 'queue' ? p.items.length + ' 集' : '规则' }}）</button>
        <Button v-if="activePl" size="sm" variant="ghost" class="ml-auto" :disabled="plBusy" @click="deletePlaylist">
          删除播放列表
        </Button>
      </div>
      <p class="mt-1.5 text-[11px] text-muted-foreground">
        内置规则与保存的规则走同一条求值路径；「从队列保存」存队列快照（不是规则）。
      </p>
      <div class="mt-2 flex flex-wrap items-end gap-2">
        <label class="flex flex-col gap-0.5">
          <span class="text-[10.5px] text-muted-foreground">名称</span>
          <input
            v-model="plName"
            aria-label="播放列表名"
            class="h-7 w-32 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
          >
        </label>
        <label class="flex flex-col gap-0.5">
          <span class="text-[10.5px] text-muted-foreground">匹配</span>
          <select v-model="plMatch" aria-label="播放列表匹配" class="h-7 rounded-md border border-border bg-card px-1 text-[11.5px] text-foreground outline-none focus:border-ring">
            <option value="all">全部满足</option>
            <option value="any">任一满足</option>
          </select>
        </label>
        <label class="flex flex-col gap-0.5">
          <span class="text-[10.5px] text-muted-foreground">字段</span>
          <select v-model="ruleField" aria-label="规则字段" class="h-7 rounded-md border border-border bg-card px-1 text-[11.5px] text-foreground outline-none focus:border-ring" @change="setRuleField">
            <option v-for="(label, key) in EPISODE_FIELD_LABELS" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-0.5">
          <span class="text-[10.5px] text-muted-foreground">操作</span>
          <select v-model="ruleOp" aria-label="规则操作" class="h-7 rounded-md border border-border bg-card px-1 text-[11.5px] text-foreground outline-none focus:border-ring">
            <option v-for="op in ruleOps" :key="op" :value="op">{{ EPISODE_OP_LABELS[op] }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-0.5">
          <span class="text-[10.5px] text-muted-foreground">值</span>
          <input
            v-model="ruleValue"
            aria-label="规则值"
            placeholder="如 unplayed / 30 / yes"
            class="h-7 w-32 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
            @keyup.enter="addDraftRule"
          >
        </label>
        <Button size="sm" variant="ghost" @click="addDraftRule">加规则</Button>
        <Button size="sm" variant="ghost" :disabled="plBusy" @click="savePlaylist">保存播放列表</Button>
        <Button size="sm" variant="ghost" :disabled="plBusy || !queue.items.length" @click="saveFromQueue">
          从队列保存
        </Button>
      </div>
      <ul v-if="draftRules.length" class="mt-1.5 space-y-0.5">
        <li v-for="(r, i) in draftRules" :key="i" class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <span class="flex-1">{{ episodeRuleText(r) }}</span>
          <button type="button" class="cursor-pointer text-destructive hover:underline" @click="removeDraftRule(i)">移除</button>
        </li>
      </ul>
      <p v-if="plMsg" class="mt-1.5 text-[11.5px] text-destructive">{{ plMsg }}</p>

      <div v-if="plTitle" class="mt-2 rounded-md border border-border p-2">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[11.5px] font-medium text-foreground">{{ plTitle }}（{{ plRows.length }} 集）</span>
          <Button size="sm" variant="ghost" class="ml-auto" :disabled="!plRows.length" @click="addAllPlToQueue">
            全部加入队列
          </Button>
        </div>
        <p v-if="!plRows.length" class="mt-1 text-[11.5px] text-muted-foreground">没有命中的单集。</p>
        <ul v-else class="mt-1 divide-y divide-border">
          <li v-for="r in plRows" :key="r.id" class="flex flex-wrap items-center gap-2 py-1.5 text-[11.5px]">
            <button
              type="button"
              class="min-w-0 flex-1 cursor-pointer truncate text-left text-foreground hover:text-primary"
              @click="playPlRow(r)"
            >{{ r.title }}</button>
            <span class="shrink-0 text-[11px] text-muted-foreground">{{ r.podcast_title }}</span>
            <span v-if="r.duration_sec" class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ fmtDuration(r.duration_sec) }}</span>
            <span v-if="r.status" class="shrink-0 text-[11px] text-muted-foreground">{{ r.status }}</span>
            <Button size="sm" variant="ghost" @click="playPlRow(r)">播放</Button>
          </li>
        </ul>
      </div>
    </Card>

    <!-- 播客版「继续收听」（第 183 期）：跨订阅，按最近播放倒序 -->
    <Card v-if="contItems.length">
      <h3 class="mb-2 text-[13px] font-semibold text-foreground">继续收听</h3>
      <ul class="divide-y divide-border">
        <li v-for="it in contItems" :key="it.id" class="flex flex-wrap items-center gap-2 py-2 text-[12px]">
          <button
            type="button"
            class="min-w-0 flex-1 cursor-pointer truncate text-left text-foreground hover:text-primary"
            @click="playContinue(it)"
          >{{ it.title }}</button>
          <span class="shrink-0 text-[11px] text-muted-foreground">{{ it.podcast_title }}</span>
          <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">
            {{ fmtPos(it.position_sec) }}<template v-if="it.duration_sec"> / {{ fmtDuration(it.duration_sec) }}</template>
          </span>
          <Button size="sm" variant="ghost" @click="playContinue(it)">继续播放</Button>
        </li>
      </ul>
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
            v-for="p in visiblePods"
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
            <div class="flex shrink-0 flex-wrap items-center gap-1">
              <select
                v-if="colls.length"
                :aria-label="`加入合集：${p.title}`"
                class="h-7 rounded-md border border-border bg-card px-1 text-[11px] text-foreground outline-none focus:border-ring"
                :disabled="collBusy"
                @change="addToColl(p, $event)"
              >
                <option value="">加入合集…</option>
                <option v-for="c in colls" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
              <Button v-if="activeCollection" size="sm" variant="ghost" :disabled="collBusy" @click="removeFromActive(p)">
                移出合集
              </Button>
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
        <p v-if="!visiblePods.length" class="px-4 py-6 text-center text-[12px] text-muted-foreground">
          这个合集还没有节目 —— 用每行的「加入合集…」把订阅加进来。
        </p>
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
        <div class="mb-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
          <span>自动下载最新</span>
          <input
            v-model.number="autoKeep"
            type="number"
            min="0"
            max="50"
            aria-label="自动下载最新集数"
            class="h-7 w-16 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
            :disabled="autoBusy"
          >
          <span>集（0 = 关闭）</span>
          <label class="ml-2 flex cursor-pointer items-center gap-1">
            <input
              v-model="autoClean"
              type="checkbox"
              class="h-3.5 w-3.5 cursor-pointer accent-primary"
              :disabled="autoBusy"
            >
            听完清理本地副本
          </label>
          <Button size="sm" variant="ghost" :disabled="autoBusy" @click="saveAuto">保存自动策略</Button>
        </div>
        <EmptyState
          v-if="!episodes.length"
          icon="volume"
          title="还没有单集"
          desc="点上面的「刷新」去发布方那里取最新一期。"
        />
        <template v-else>
          <!-- 播放队列（第 180 期）：播完优先取队首；跨订阅也允许 -->
          <div v-if="queue.items.length" class="mb-2 rounded-md border border-border p-2">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-[11.5px] font-medium text-muted-foreground">
                播放队列（{{ queue.items.length }}）
              </span>
              <Button size="sm" variant="ghost" class="ml-auto" @click="queue.clear()">清空</Button>
            </div>
            <ul class="mt-1 space-y-0.5">
              <li v-for="it in queue.items" :key="it.episodeId" class="flex items-center gap-2 text-[11.5px]">
                <button
                  type="button"
                  class="min-w-0 flex-1 cursor-pointer truncate text-left text-foreground hover:text-primary"
                  @click="playQueueItem(it)"
                >{{ it.title }}</button>
                <span class="shrink-0 text-muted-foreground">{{ it.podcastTitle }}</span>
                <button
                  type="button"
                  class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-destructive"
                  @click="queue.remove(it.episodeId)"
                >移除</button>
              </li>
            </ul>
          </div>
          <div class="mb-2 flex flex-wrap items-center gap-1">
            <input
              v-model="q"
              type="search"
              aria-label="搜索单集"
              placeholder="搜索单集…"
              class="h-7 w-40 rounded-md border border-border bg-card px-2 text-[11.5px] text-foreground outline-none focus:border-ring"
            >
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
              <button
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-primary hover:underline"
                @click="toggleQueue(e)"
              >{{ queue.has(e.id) ? '移出队列' : '加入队列' }}</button>
              <button
                v-if="e.has_transcript"
                type="button"
                class="shrink-0 cursor-pointer text-[11px] text-primary hover:underline"
                @click="toggleTranscript(e)"
              >转录</button>
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
            <div v-if="trFor === e.id" class="mt-1.5 rounded-md border border-border bg-muted/30 p-2">
              <div class="text-[11px] text-muted-foreground">官方转录</div>
              <p v-if="trBusy" class="mt-1 text-[11px] text-muted-foreground">读取中…</p>
              <p v-else-if="trReason" class="mt-1 text-[11px] text-muted-foreground">{{ trReason }}</p>
              <pre v-else class="mt-1 max-h-[16rem] overflow-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-foreground">{{ trText }}</pre>
            </div>
          </li>
        </ul>
        </template>
      </Card>
    </template>
  </div>
</template>
