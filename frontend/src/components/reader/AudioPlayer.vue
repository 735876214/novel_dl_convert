<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type AudioTrack, type Bookmark, type SessionExtra, type UnitPos, type UnitRef } from '@/lib/api'
import {
  AUDIO_SKIP_BACKS,
  AUDIO_SLEEPS,
  AUDIO_SLEEP_TRACK_END,
  AUDIO_SPEED_MAX,
  AUDIO_SPEED_MIN,
  AUDIO_SPEED_STEP,
  AUDIO_SPEEDS,
  readAudioPrefs,
} from '@/lib/audioPrefs'
import { createSessionReporter } from '@/lib/readingSession'
import { useSeriesNext } from '@/lib/seriesNext'
import { fromPercent, toPercent } from '@/lib/unitsProgress'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 有声书播放器（单文件 / 多轨目录通用）。
 *
 * 进度语义：`progress.locator` = **当前轨内的秒数**，`percent` = 按轨加权的全书进度。
 * 恢复时由 percent 反推轨号、再由 locator 定位秒数 —— 单轨书（最常见）完全精确，
 * 多轨书在轨长相近时也够用。
 *
 * **单话模式**（第 73 期）：给 `unit` 时本组件只播「序号单元合集里的这一话」——
 * 数据源换成 `/units/{index}`、进度**不读不写**（整本书的 percent 由上层 `UnitsReader`
 * 独占，见那里的说明），放完发 `unitEnd` 让上层翻下一话。
 */
const props = defineProps<{
  bookId: string
  /** 多轨模式下的轨清单；单话模式（给了 `unit`）下**不使用**它 */
  tracks: AudioTrack[]
  series?: string
  /** 单话模式：正在播的那一话（`index` / `total` / `within` 见 `api.UnitRef`） */
  unit?: UnitRef | null
  /** 单话模式：挂载后自动开播（上一话放完自动续过来时用；用户点目录换话时不自动播） */
  autoplay?: boolean
}>()

/** 单话模式下的上报：话内进度 + 话内位置（秒）。上层据此拼整本书的 percent 并落盘 */
const emit = defineEmits<{ unitPos: [UnitPos]; unitEnd: [] }>()

const ui = useUiStore()
const library = useLibraryStore()
/** 自动翻到系列下一册（第 66 期）：实现收敛到 `lib/seriesNext.ts` 单一真值源 */
const { goToNextVolume } = useSeriesNext()
const prefs = readAudioPrefs()

const audio = ref<HTMLAudioElement | null>(null)
const index = ref(0)
const playing = ref(false)
const duration = ref(0)
const currentTime = ref(0)
const ready = ref(false)
const error = ref('')

// ---------------- 书签（第 167 期）----------------
// 复用既有 `bookmarks` 表：anchor 编码音频坐标 `audio:<轨号>:<轨内秒>`，`chapter` = 轨号，
// `percent` = 整本书百分比（与进度同一把尺子）。**单话模式不做书签**：一话一个
// `AudioPlayer` 实例，书签应属于整本书而不是某一话的临时实例（如实留到合集阅读器再说）。
const bookmarks = ref<Bookmark[]>([])
const bmDraft = ref('')
const bmBusy = ref(false)
const AUDIO_ANCHOR = 'audio:'

function loadBookmarks(): void {
  if (unitMode.value) return
  api.listBookmarks(props.bookId)
    .then((r) => {
      bookmarks.value = (r.items || []).filter((b) => String(b.anchor || '').startsWith(AUDIO_ANCHOR))
    })
    .catch(() => { /* 书签读不到不影响播放；下次进页再试 */ })
}

/** `audio:<轨号>:<秒>` → 坐标；坏锚（历史数据 / 手改）按 0 处理，不让整页炸 */
function bmPos(b: Bookmark): { track: number; sec: number } {
  const parts = String(b.anchor || '').split(':')
  return { track: Math.max(0, Number(parts[1]) || 0), sec: Math.max(0, Number(parts[2]) || 0) }
}

function bmText(b: Bookmark): string {
  const { track, sec } = bmPos(b)
  return total.value > 1 ? `第 ${track + 1} 轨 · ${fmt(sec)}` : fmt(sec)
}

async function addBookmarkHere(): Promise<void> {
  if (unitMode.value || bmBusy.value || !ready.value) return
  const track = index.value
  const sec = Math.floor(currentTime.value)
  const anchor = `${AUDIO_ANCHOR}${track}:${sec}`
  const fallback = total.value > 1 ? `第 ${track + 1} 轨 ${fmt(sec)}` : fmt(sec)
  bmBusy.value = true
  try {
    await api.addBookmark(props.bookId, {
      anchor,
      chapter: track,
      percent: Math.round(percent.value),
      label: bmDraft.value.trim() || fallback,
    })
    bmDraft.value = ''
    loadBookmarks()
    ui.toast('已加书签')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '加书签失败')
  } finally {
    bmBusy.value = false
  }
}

/** 跳到书签：换轨后在元数据到达时定位到秒数；同轨且已就绪就直接跳 */
function jumpBookmark(b: Bookmark): void {
  const { track, sec } = bmPos(b)
  if (track !== index.value) goto(track, false)
  if (ready.value && track === index.value) seekTo(sec)
  else seekWhenReady(sec)
  void audio.value?.play().catch(() => { /* 浏览器拦住就等用户点播放 */ })
}

async function removeBookmark(b: Bookmark): Promise<void> {
  try {
    await api.deleteBookmark(props.bookId, b.id)
    loadBookmarks()
    ui.toast('书签已移入垃圾桶')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

// ---------------- 单轨「已听」标记（第 168 期）----------------
// 数据来源只有一处：`reading_sessions.file_rel`（播放器把当前轨 basename 当会话标签）。
// **没有手动标记** —— 听过就是有过收听会话，未听就是没有。
const heard = ref<Set<string>>(new Set())

function loadHeard(): void {
  if (unitMode.value) return
  api.audioHeard(props.bookId)
    .then((r) => { heard.value = new Set(r.items || []) })
    .catch(() => { /* 读不到就不显示标记，不影响播放 */ })
}

const speed = ref(prefs.speed)
const volume = ref(prefs.volume)
const skipBack = ref(prefs.skipBack)
const skipForward = ref(prefs.skipForward)
type SleepChoice = 'off' | '15' | '30' | '60' | '90' | typeof AUDIO_SLEEP_TRACK_END
/** 细调后的倍速可能不在预设档位里 —— 下拉要能显示它（否则 select 会显示空白） */
const speedIsPreset = computed(() => (AUDIO_SPEEDS as readonly number[]).includes(speed.value))

/** 睡眠模式：数字档位 = 倒计时；track-end = 本轨播完暂停（第 169 期） */
const sleepChoice = ref<SleepChoice>(
  prefs.sleepMinutes ? (String(prefs.sleepMinutes) as SleepChoice) : 'off',
)
const sleepMinutes = ref(prefs.sleepMinutes)
const sleepLeft = ref(0)          // 剩余秒数（0 = 未启用）
const sleepAtTrackEnd = ref(false)
let sleepTimer: number | undefined

/** 单话模式：播的是合集里的一个文件，不是「一本书的若干轨」 */
const unitMode = computed(() => !!props.unit)
const total = computed(() => (unitMode.value ? 1 : props.tracks.length))
const current = computed<AudioTrack | null>(() => (unitMode.value ? null : props.tracks[index.value] ?? null))

/**
 * 轨列表的**渲染窗口**（第 152 期审计实测）：最长的一本有声书有 7,464 轨，全量进 DOM
 * 是 **30,211 个节点 / 7,508 个按钮**，单次长任务 1.1 秒 —— 而那块列表只有 280px 高。
 * 默认渲染 200 条，底部「显示更多」每次再加 500；**当前轨永远在窗口内**（从进度恢复
 * 到第 6,000 轨时也不会出现「高亮项在窗口外」）。
 */
const TRACK_WINDOW = 200
const TRACK_MORE = 500
const trackLimit = ref(TRACK_WINDOW)
const shownTracks = computed(() => {
  const n = props.tracks.length
  const size = Math.min(n, Math.max(1, trackLimit.value))
  if (n <= size) return props.tracks
  // **以当前轨为中心开窗**：只取前缀的话，从第 6,000 轨续播时仍要渲染前 6,001 条
  // （第 152 期审计实测指出的第一版缺陷）。窗口随 `index` 移动，当前轨永远在可见区。
  const half = Math.floor(size / 2)
  const start = index.value < half ? 0 : Math.min(index.value - half, n - size)
  return props.tracks.slice(start, start + size)
})
function showMoreTracks(): void {
  trackLimit.value += TRACK_MORE
}
// 换书时窗口复位（组件可能被复用）
watch(() => props.bookId, () => { trackLimit.value = TRACK_WINDOW; loadBookmarks(); loadHeard() })
const src = computed(() => {
  if (unitMode.value) return props.unit ? api.unitFileUrl(props.bookId, props.unit.index) : ''
  return current.value ? api.audioTrackUrl(props.bookId, index.value) : ''
})
/** 这一轨（单话模式下 = 这一话）播到哪：0–1。时长还没读到按 0 算（= 这一话的开头） */
const within = computed(() => (duration.value ? Math.min(1, Math.max(0, currentTime.value / duration.value)) : 0))
/**
 * 全书百分比。两个模式的算式**同一份**（`lib/unitsProgress.toPercent`）：
 * 单话模式下 `total` 是**整本书的话数**、`index` 是这一话在书里的位置 ——
 * 于是「第 3 话播到一半」落在同一把尺子上，与多轨模式逐字相同。
 * ⚠️ 别在这里另写一遍除法：`AudioPlayer` 与 `UnitsReader` 各写一份就是两个真相源。
 */
const percent = computed(() => (unitMode.value
  ? toPercent(props.unit?.index ?? 0, within.value, props.unit?.total ?? 1)
  : toPercent(index.value, within.value, Math.max(1, total.value))))

function fmt(sec: number): string {
  if (!Number.isFinite(sec) || sec < 0) sec = 0
  const s = Math.floor(sec % 60)
  const m = Math.floor(sec / 60) % 60
  const h = Math.floor(sec / 3600)
  const mm = h ? String(m).padStart(2, '0') : String(m)
  return `${h ? `${h}:` : ''}${mm}:${String(s).padStart(2, '0')}`
}

// ---------------- 播放控制 ----------------

function toggle(): void {
  const el = audio.value
  if (!el) return
  if (el.paused) void el.play().catch((e) => (error.value = String(e)))
  else el.pause()
}

function seekTo(sec: number): void {
  const el = audio.value
  if (!el || !duration.value) return
  el.currentTime = Math.max(0, Math.min(duration.value, sec))
  currentTime.value = el.currentTime
}

function skip(delta: number): void {
  seekTo(currentTime.value + delta)
}

function goto(i: number, autoplay = true): void {
  if (i < 0 || i >= total.value) return
  index.value = i
  ready.value = false
  const el = audio.value
  if (el) el.currentTime = 0
  currentTime.value = 0
  if (autoplay) {
    // 等 src 变更后由 watch(src) 触发 play
    window.setTimeout(() => void audio.value?.play().catch(() => {}), 0)
  }
}

// ---------------- 事件 ----------------

/**
 * 会话上报（第 63 期）：一次连续收听 = 一段（同一个 `session_uid` = 数据库一行）。
 *
 * ⚠️ 与阅读器**不同**，这里不看 `document.visibilityState`：屏幕关掉、切到别的标签页时
 * 有声书照常在放，那就是在听 —— 按可见性算会把「睡前戴着耳机听两小时」记成 0。
 * 「是不是在读」的判据只有一条：**音频在不在播**。
 */
const session = createSessionReporter({
  source: 'audio',
  // 位置快照的 `percent` 两个模式都是**整本书**的百分比（单话模式下由 `index/total` 换算，
  // 见上面的 `percent`）；`locator` 是轨号 / 话号 —— 同一把尺子，阅读日志的「读到哪」才连得上。
  snapshot: () => ({ percent: percent.value, locator: unitMode.value ? (props.unit?.index ?? 0) : index.value }),
  // 多轨有声书带上当前轨的文件名，服务端据此把这段时长归到**这一轨**。
  // 单轨书不给：空串的含义是「这本书自己」，不是「不知道哪一轨」。
  // 单话模式给的是**话的库内相对路径**（与 `UnitItem.name` 同源），它本身就是这条约定的取值。
  fileRel: () => (unitMode.value
    ? props.unit?.name
    : total.value > 1 ? current.value?.name : undefined),
  post: (secs, extra: SessionExtra) => api.recordSession(props.bookId, secs, extra),
})

let lastTick = 0

function onLoaded(): void {
  const el = audio.value
  if (!el) return
  ready.value = true
  duration.value = el.duration || 0
  el.playbackRate = speed.value
  el.volume = volume.value
}

function onTime(): void {
  const el = audio.value
  if (!el) return
  currentTime.value = el.currentTime
  if (playing.value) {
    const now = Date.now()
    if (lastTick) session.accrue((now - lastTick) / 1000)
    lastTick = now
    // 每满一分钟落一次（原来的节奏），免得长时间收听只在暂停时才上报
    if (session.pending >= 60) void session.flush()
  }
  // 每 5 秒落一次进度，避免频繁写库
  if (Math.floor(currentTime.value) % 5 === 0) saveProgress()
}

async function onEnded(): Promise<void> {
  // 睡眠「本轨结束」：自然播完就停在原地（不续下一轨 / 下一话）
  if (sleepAtTrackEnd.value) {
    audio.value?.pause()
    sleepAtTrackEnd.value = false
    sleepChoice.value = 'off'
    ui.toast('本轨结束，已按睡眠定时暂停')
    return
  }
  if (unitMode.value) {
    // 单话模式：这一话放完了。先上报末尾位置，再决定「续下一话」还是「跨册续接」
    reportUnitPos()
    session.pause()
    void session.flush()
    const u = props.unit
    if (u && u.index + 1 < u.total) {
      emit('unitEnd')       // 书内还有下一话 ⇒ 交给上层换话（上层会决定要不要自动开播）
      return
    }
    // 已经是最后一话：回到「读完 → 自动翻下一册」那套（开关 / 系列提示 / 跳转都不变）
    const advanced = await goToNextVolume({
      enabled: prefs.autoNextBook,
      series: props.series,
      bookId: props.bookId,
      routeBase: '/listen',
    })
    if (!advanced) playing.value = false
    return
  }
  if (index.value + 1 < total.value) {
    // 同册内「轨与轨」续接是内置行为，直接进下一轨
    goto(index.value + 1)
    return
  }
  // 最后一轨放完：先落盘，再决定跨册续接还是停下
  saveProgress()
  session.pause()
  void session.flush().then(loadHeard)
  // 跨册续接（第 61 期起；第 66 期收敛到 `lib/seriesNext.ts` 单一真值源）：
  // 开关关着时静默停下；开着则**无系列也会如实提示**（此前是静默停下）。
  const advanced = await goToNextVolume({
    enabled: prefs.autoNextBook,
    series: props.series,
    bookId: props.bookId,
    routeBase: '/listen',
  })
  if (!advanced) playing.value = false
}

function onPlay(): void {
  playing.value = true
  lastTick = Date.now()
  // 暂停超过半小时再接着听，算新的一段（`pause()` 时记下了离开时刻）
  session.resume()
}

function onPause(): void {
  playing.value = false
  lastTick = 0
  saveProgress()
  session.pause()
  void session.flush().then(loadHeard)
}

/**
 * 单话模式的上报：把「这一话读到哪」交给上层（`UnitsReader`）。
 *
 * ⚠️ 单话模式下本组件**绝不写进度** —— 整本书只有一行 `percent`，写它需要
 * 「第几话 + 这一话内多少」两个数（见 `lib/unitsProgress.ts`）；上层手里才有完整的那份。
 * 子组件各写一半必然互相覆盖：「切到第 4 话时第 3 话的卸载钩子把进度写回第 3 话」。
 *
 * `locator` 沿用「轨内秒数」的语义（与多轨模式同一个字段、同一把尺子）。
 */
function reportUnitPos(): void {
  if (!unitMode.value) return
  emit('unitPos', { index: props.unit?.index ?? 0, within: within.value, locator: currentTime.value })
}

function saveProgress(): void {
  if (unitMode.value) {
    reportUnitPos()
    return
  }
  const pct = Math.round(percent.value)
  // ⚠️ 这里**刻意不带 file_rel**（第 63 期 4/6 给其余三个阅读器都加上了，音频不加），
  // 三条理由，都不是「漏了」：
  // 1. 有声书在库里是**一个目录**，`library.book_detail` 对目录**跳过**同 stem 枚举
  //    （见那里的注释），于是 `files` 是空的 —— 「多文件」这件事在有声书上不存在，
  //    带上只会把书级那行从 `''` 挪到一个没有意义的键上；
  // 2. 下面 `session` 那边传给 `reading_sessions.file_rel` 的是 `AudioTrack.name`，
  //    那是**文件名 basename**（`audio.py` 给的是 `f.name`），**不是库根相对路径**。
  //    它当会话标签没问题，但当 `progress.file_rel` 不行 —— 服务端会拿它走
  //    `fileops.safe_path` 拼路径（生成 CFI 那一步），basename 拼出来是错路径。
  //    同一个列名在两处的**实际约束不同**：那边纯标签，这边会当路径用。
  // 3. 音频的读点本来就只有一个：`percent`（全书百分比）已经编码了「第几轨」，
  //    `locator` 是轨内秒数 —— 一轨一行反而把一件事拆成 N 行。
  void api.setProgress(props.bookId, Math.round(currentTime.value), pct)
    .then((r) => {
      // 第 61 期：进度就地回写 store（首页「继续阅读」实时）
      library.patchProgress(props.bookId, pct, r?.updated_at)
    })
    .catch(() => {})
}

// ---------------- 睡眠定时 ----------------

function clearSleepTimer(): void {
  if (sleepTimer) { window.clearInterval(sleepTimer); sleepTimer = undefined }
}

/**
 * 设置睡眠模式（第 169 期）：数字档位 = 倒计时，`track-end` = **本轨播完就暂停**。
 *
 * 「本轨结束」只在**自然播完**时停（`onEnded`）—— 用户手动切轨/拖进度不该被它拦住，
 * 那是明确的操作意图，不是「睡前放着」。
 */
function setSleep(choice: SleepChoice): void {
  sleepChoice.value = choice
  sleepAtTrackEnd.value = choice === AUDIO_SLEEP_TRACK_END
  clearSleepTimer()
  if (sleepAtTrackEnd.value) {
    sleepLeft.value = 0
    sleepMinutes.value = 0
    return
  }
  const mins = choice === 'off' ? 0 : Number(choice)
  sleepMinutes.value = Number.isFinite(mins) ? mins : 0
  if (!sleepMinutes.value) { sleepLeft.value = 0; return }
  sleepLeft.value = sleepMinutes.value * 60
  sleepTimer = window.setInterval(() => {
    sleepLeft.value -= 1
    if (sleepLeft.value <= 0) {
      audio.value?.pause()
      clearSleepTimer()
      sleepLeft.value = 0
      sleepMinutes.value = 0
      sleepChoice.value = 'off'
      ui.toast('睡眠定时结束，已暂停播放')
    }
  }, 1000)
}

function onSleepChange(e: Event): void {
  setSleep((e.target as HTMLSelectElement).value as SleepChoice)
}

/** 「+15 分钟」：倒计时中延长；本来没开就开 15 分钟。本轨结束模式没有倒计时可延。 */
function extendSleep(): void {
  if (sleepAtTrackEnd.value) return
  if (sleepLeft.value > 0) { sleepLeft.value += 15 * 60; return }
  setSleep('15')
}

/** 倍速细调（第 169 期）：按 0.05 步进并夹在 0.5–3，避免出现 3.0000001 这类浮点尾巴。 */
function nudgeSpeed(delta: number): void {
  const next = Math.round((Number(speed.value) + delta) * 100) / 100
  speed.value = Math.min(AUDIO_SPEED_MAX, Math.max(AUDIO_SPEED_MIN, next))
}

// 改变倍速 / 音量立即生效
watch(speed, (v) => { if (audio.value) audio.value.playbackRate = v })
watch(volume, (v) => { if (audio.value) audio.value.volume = v })
watch(src, () => { ready.value = false })

/** 等元数据到了再跳转（时长是这时候才知道的） */
function seekWhenReady(seconds: number): void {
  if (!(seconds > 0)) return
  const seek = () => {
    seekTo(seconds)
    duration.value = audio.value?.duration || 0
    audio.value?.removeEventListener('loadedmetadata', seek)
  }
  audio.value?.addEventListener('loadedmetadata', seek)
}

onMounted(async () => {
  session.begin()
  loadBookmarks()
  loadHeard()
  if (unitMode.value) {
    // 单话模式：恢复到哪由上层给（`within`，0–1 的**话内**比例），**不问服务端** ——
    // 书级的 percent 是整本书的坐标，子阅读器手里没有 `total` 语义（话数 ≠ 轨数）就换不出来。
    const w = props.unit?.within ?? 0
    if (w > 0) {
      const el = audio.value
      const seek = () => {
        seekTo(w * (el?.duration || 0))
        duration.value = el?.duration || 0
        el?.removeEventListener('loadedmetadata', seek)
      }
      el?.addEventListener('loadedmetadata', seek)
    }
    // 上一话放完自动续过来的那一话自动开播（用户点目录换话时不自动播 —— 那是明确的「我要看这一话」）
    if (props.autoplay) void audio.value?.play().catch(() => { /* 浏览器拦住就等用户点播放 */ })
    if (sleepChoice.value !== 'off') setSleep(sleepChoice.value)
    return
  }
  try {
    const p = await api.getProgress(props.bookId)
    if (p && p.percent > 0 && total.value > 1) {
      // 反推轨号走**唯一真值源**（`lib/unitsProgress`），别在这里再写一遍 floor ——
      // 两份算式的浮点边界处理只要有一处走样，「书架说读到第 5 轨、点进去从第 4 轨开始」
      // 就会重新出现，而且不报错。
      index.value = fromPercent(p.percent, total.value).index
    }
    if (p && p.locator > 0) seekWhenReady(p.locator)
  } catch {
    /* 无进度从头发起 */
  }
  if (sleepChoice.value !== 'off') setSleep(sleepChoice.value)
})

onBeforeUnmount(() => {
  if (sleepTimer) window.clearInterval(sleepTimer)
  saveProgress()
  void session.stop()
})
</script>

<template>
  <div>
    <audio
      ref="audio"
      :src="src"
      preload="metadata"
      class="hidden"
      @loadedmetadata="onLoaded"
      @timeupdate="onTime"
      @play="onPlay"
      @pause="onPause"
      @ended="onEnded"
      @error="error = '音频加载失败（文件可能已损坏或格式不被浏览器支持）'"
    />

    <!-- 进度条 -->
    <div class="mt-1">
      <input
        type="range" min="0" :max="duration || 0" step="0.5" :value="currentTime"
        :disabled="!ready"
        class="h-1.5 w-full cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-50"
        @input="seekTo(Number(($event.target as HTMLInputElement).value))"
      >
      <div class="mt-1 flex justify-between text-[11px] text-muted-foreground tabular-nums">
        <span>{{ fmt(currentTime) }}</span>
        <span>{{ ready ? fmt(duration) : '--:--' }}</span>
      </div>
    </div>

    <!-- 主控件 -->
    <div class="mt-3 flex items-center justify-center gap-3">
      <button
        v-if="!unitMode"
        type="button"
        class="cursor-pointer rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        :disabled="index === 0" title="上一轨" @click="goto(index - 1)"
      >
        <Icon name="skipBack" class="h-4 w-4" />
      </button>
      <button
        type="button"
        class="cursor-pointer rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        :title="`快退 ${skipBack} 秒`" @click="skip(-skipBack)"
      >
        <span class="text-[11px] font-medium tabular-nums">-{{ skipBack }}s</span>
      </button>
      <button
        type="button"
        class="flex h-14 w-14 cursor-pointer items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm transition-transform duration-150 hover:scale-105 active:scale-95"
        :title="playing ? '暂停' : '播放'" @click="toggle"
      >
        <Icon :name="playing ? 'pause' : 'play'" class="h-6 w-6" />
      </button>
      <button
        type="button"
        class="cursor-pointer rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        :title="`快进 ${skipForward} 秒`" @click="skip(skipForward)"
      >
        <span class="text-[11px] font-medium tabular-nums">+{{ skipForward }}s</span>
      </button>
      <button
        v-if="!unitMode"
        type="button"
        class="cursor-pointer rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        :disabled="index >= total - 1" title="下一轨" @click="goto(index + 1)"
      >
        <Icon name="skipForward" class="h-4 w-4" />
      </button>
    </div>

    <!-- 书签（第 167 期）：时间点 + 备注；复用 bookmarks 表，anchor = audio:<轨>:<秒> -->
    <div v-if="!unitMode" class="mt-4 border-t border-border pt-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[11.5px] font-medium text-muted-foreground">书签</span>
        <input
          v-model="bmDraft"
          type="text"
          aria-label="书签备注"
          placeholder="备注（可空）"
          class="h-7 min-w-[8rem] flex-1 rounded-md border border-border bg-card px-2 text-[11.5px] text-foreground outline-none focus:border-ring"
          @keyup.enter="addBookmarkHere"
        >
        <Button size="sm" :disabled="!ready || bmBusy" @click="addBookmarkHere">
          加在当前时间
        </Button>
      </div>
      <ul v-if="bookmarks.length" class="mt-1.5 max-h-[10rem] space-y-0.5 overflow-auto">
        <li
          v-for="b in bookmarks"
          :key="b.id"
          class="flex items-center gap-2 rounded px-1 py-0.5 hover:bg-muted"
        >
          <button
            type="button"
            class="shrink-0 cursor-pointer font-mono text-[11.5px] text-primary tabular-nums hover:underline"
            :title="`跳到 ${bmText(b)}`"
            @click="jumpBookmark(b)"
          >
            {{ bmText(b) }}
          </button>
          <span class="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground">{{ b.label }}</span>
          <button
            type="button"
            class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-destructive"
            @click="removeBookmark(b)"
          >
            删除
          </button>
        </li>
      </ul>
      <p v-else class="mt-1 text-[11px] text-muted-foreground">
        还没有书签。播放到想记的位置，点「加在当前时间」。
      </p>
    </div>

    <!-- 倍速 / 音量 / 睡眠定时 -->
    <div class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-border pt-3">
      <!-- ⚠️ 用 div 不用 label：按钮也是 labelable 元素，label 的点击转发会把
           「点 +」再转成「点第一个按钮（−）」，步进互相抵消（第 169 期 vitest 实测）。 -->
      <div class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <span>倍速</span>
        <button
          type="button"
          class="h-6 w-6 cursor-pointer rounded border border-border text-[12px] leading-none text-foreground transition-colors hover:bg-muted disabled:opacity-40"
          title="降 0.05 倍速"
          :disabled="speed <= AUDIO_SPEED_MIN"
          @click="nudgeSpeed(-AUDIO_SPEED_STEP)"
        >−</button>
        <select
          v-model.number="speed"
          aria-label="播放倍速"
          class="rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
          <option v-if="!speedIsPreset" :value="speed">{{ speed }}x（细调）</option>
          <option v-for="s in AUDIO_SPEEDS" :key="s" :value="s">{{ s }}x</option>
        </select>
        <button
          type="button"
          class="h-6 w-6 cursor-pointer rounded border border-border text-[12px] leading-none text-foreground transition-colors hover:bg-muted disabled:opacity-40"
          title="升 0.05 倍速"
          :disabled="speed >= AUDIO_SPEED_MAX"
          @click="nudgeSpeed(AUDIO_SPEED_STEP)"
        >+</button>
      </div>

      <label class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Icon name="volume" class="h-3.5 w-3.5" />
        <input v-model.number="volume" type="range" min="0" max="1" step="0.05" class="w-24 cursor-pointer accent-primary">
      </label>

      <div class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Icon name="moon" class="h-3.5 w-3.5" />
        <span>睡眠</span>
        <select
          :value="sleepChoice"
          aria-label="睡眠定时"
          class="rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          @change="onSleepChange"
        >
          <option value="off">关闭</option>
          <option v-for="m in AUDIO_SLEEPS.filter((x) => x > 0)" :key="m" :value="String(m)">{{ m }} 分钟</option>
          <option :value="AUDIO_SLEEP_TRACK_END">本轨结束</option>
        </select>
        <button
          v-if="sleepChoice !== 'off' && !sleepAtTrackEnd"
          type="button"
          class="cursor-pointer rounded border border-border px-1.5 py-0.5 text-[11px] text-foreground transition-colors hover:bg-muted"
          title="延长 15 分钟"
          @click="extendSleep"
        >+15 分钟</button>
        <span v-if="sleepLeft" class="tabular-nums text-primary">{{ fmt(sleepLeft) }}</span>
        <span v-else-if="sleepAtTrackEnd" class="text-primary">本轨结束</span>
      </div>

      <span class="ml-auto text-[11px] text-muted-foreground">
        跳转间隔：快退 {{ skipBack }}s / 快进 {{ skipForward }}s（可在设置里改）
      </span>
    </div>

    <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>

    <!-- 轨道列表（多轨时才有意义） -->
    <div v-if="total > 1" class="mt-4 border-t border-border pt-3">
      <div class="mb-2 flex items-center gap-2 text-[11.5px] font-medium text-muted-foreground">
        <span>共 {{ total }} 轨</span>
        <span v-if="heard.size" class="text-[11px] text-muted-foreground/80">已听 {{ heard.size }}</span>
      </div>
      <ol class="max-h-[280px] space-y-0.5 overflow-auto">
        <li v-for="t in shownTracks" :key="t.index">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors"
            :class="t.index === index ? 'bg-[var(--shell-accent-tint)] text-primary' : 'text-foreground/90 hover:bg-muted'"
            @click="goto(t.index)"
          >
            <Icon v-if="t.index === index && playing" name="play" class="h-3 w-3 shrink-0" />
            <span v-else class="w-3 shrink-0 text-center text-[10.5px] text-muted-foreground tabular-nums">{{ t.index + 1 }}</span>
            <span class="min-w-0 flex-1 truncate">{{ t.name }}</span>
            <span
              v-if="heard.has(t.name)"
              class="shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground"
              title="听过这一轨（由收听会话派生）"
            >已听</span>
          </button>
        </li>
      </ol>
      <!-- 轨道多时先只渲染一窗（见 `shownTracks` 的注释）；这一条是**显式**的「还有多少」，
           不做无限滚动的自动加载 —— 那会在用户只是往下翻找某一轨时把列表越拉越长。 -->
      <button
        v-if="shownTracks.length < total"
        type="button"
        class="mt-1 w-full cursor-pointer rounded-md px-2 py-1.5 text-center text-[11.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        @click="showMoreTracks"
      >
        显示更多（还有 {{ total - shownTracks.length }} 轨）
      </button>
    </div>
  </div>
</template>
