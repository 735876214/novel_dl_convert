<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type AudioTrack } from '@/lib/api'
import { AUDIO_SKIP_BACKS, AUDIO_SKIP_FORWARDS, AUDIO_SLEEPS, AUDIO_SPEEDS, readAudioPrefs } from '@/lib/audioPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * 有声书播放器（单文件 / 多轨目录通用）。
 *
 * 进度语义：`progress.locator` = **当前轨内的秒数**，`percent` = 按轨加权的全书进度。
 * 恢复时由 percent 反推轨号、再由 locator 定位秒数 —— 单轨书（最常见）完全精确，
 * 多轨书在轨长相近时也够用。
 */
const props = defineProps<{ bookId: string; tracks: AudioTrack[] }>()

const ui = useUiStore()
const prefs = readAudioPrefs()

const audio = ref<HTMLAudioElement | null>(null)
const index = ref(0)
const playing = ref(false)
const duration = ref(0)
const currentTime = ref(0)
const ready = ref(false)
const error = ref('')

const speed = ref(prefs.speed)
const volume = ref(prefs.volume)
const skipBack = ref(prefs.skipBack)
const skipForward = ref(prefs.skipForward)
const sleepMinutes = ref(prefs.sleepMinutes)
const sleepLeft = ref(0)          // 剩余秒数（0 = 未启用）
let sleepTimer: number | undefined

const total = computed(() => props.tracks.length)
const current = computed<AudioTrack | null>(() => props.tracks[index.value] ?? null)
const src = computed(() => (current.value ? api.audioTrackUrl(props.bookId, index.value) : ''))
const percent = computed(() => {
  if (!duration.value) return 0
  const within = (currentTime.value / duration.value) || 0
  return ((index.value + within) / Math.max(1, total.value)) * 100
})

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

let sessionSeconds = 0
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
    if (lastTick) sessionSeconds += (now - lastTick) / 1000
    lastTick = now
    if (sessionSeconds >= 60) flushSession()
  }
  // 每 5 秒落一次进度，避免频繁写库
  if (Math.floor(currentTime.value) % 5 === 0) saveProgress()
}

function onEnded(): void {
  if (index.value + 1 < total.value) goto(index.value + 1)
  else {
    playing.value = false
    saveProgress()
    flushSession()
  }
}

function onPlay(): void {
  playing.value = true
  lastTick = Date.now()
}

function onPause(): void {
  playing.value = false
  lastTick = 0
  saveProgress()
  flushSession()
}

function saveProgress(): void {
  void api.setProgress(props.bookId, Math.round(currentTime.value), Math.round(percent.value))
    .catch(() => {})
}

function flushSession(): void {
  if (sessionSeconds < 5) return
  const secs = Math.round(sessionSeconds)
  sessionSeconds = 0
  void api.recordSession(props.bookId, secs).catch(() => {})
}

// ---------------- 睡眠定时 ----------------

function applySleep(): void {
  if (sleepTimer) { window.clearInterval(sleepTimer); sleepTimer = undefined }
  if (!sleepMinutes.value) { sleepLeft.value = 0; return }
  sleepLeft.value = sleepMinutes.value * 60
  sleepTimer = window.setInterval(() => {
    sleepLeft.value -= 1
    if (sleepLeft.value <= 0) {
      audio.value?.pause()
      if (sleepTimer) { window.clearInterval(sleepTimer); sleepTimer = undefined }
      sleepLeft.value = 0
      sleepMinutes.value = 0
      ui.toast('睡眠定时结束，已暂停播放')
    }
  }, 1000)
}

// 改变倍速 / 音量立即生效
watch(speed, (v) => { if (audio.value) audio.value.playbackRate = v })
watch(volume, (v) => { if (audio.value) audio.value.volume = v })
watch(src, () => { ready.value = false })

onMounted(async () => {
  try {
    const p = await api.getProgress(props.bookId)
    if (p && p.percent > 0 && total.value > 1) {
      const i = Math.min(total.value - 1, Math.max(0, Math.floor((p.percent / 100) * total.value)))
      index.value = i
    }
    if (p && p.locator > 0) {
      // 等 canplay 后再定位
      const seek = () => { seekTo(p.locator); duration.value = audio.value?.duration || 0; audio.value?.removeEventListener('loadedmetadata', seek) }
      audio.value?.addEventListener('loadedmetadata', seek)
    }
  } catch {
    /* 无进度从头发起 */
  }
  applySleep()
})

onBeforeUnmount(() => {
  if (sleepTimer) window.clearInterval(sleepTimer)
  saveProgress()
  flushSession()
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
        type="button"
        class="cursor-pointer rounded-full p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-40"
        :disabled="index >= total - 1" title="下一轨" @click="goto(index + 1)"
      >
        <Icon name="skipForward" class="h-4 w-4" />
      </button>
    </div>

    <!-- 倍速 / 音量 / 睡眠定时 -->
    <div class="mt-4 flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-border pt-3">
      <label class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        倍速
        <select
          v-model.number="speed"
          class="rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
          <option v-for="s in AUDIO_SPEEDS" :key="s" :value="s">{{ s }}x</option>
        </select>
      </label>

      <label class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Icon name="volume" class="h-3.5 w-3.5" />
        <input v-model.number="volume" type="range" min="0" max="1" step="0.05" class="w-24 cursor-pointer accent-primary">
      </label>

      <label class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <Icon name="moon" class="h-3.5 w-3.5" />
        睡眠
        <select
          v-model.number="sleepMinutes"
          class="rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          @change="applySleep"
        >
          <option v-for="m in AUDIO_SLEEPS" :key="m" :value="m">{{ m ? `${m} 分钟` : '关闭' }}</option>
        </select>
        <span v-if="sleepLeft" class="tabular-nums text-primary">{{ fmt(sleepLeft) }}</span>
      </label>

      <span class="ml-auto text-[11px] text-muted-foreground">
        跳转间隔：快退 {{ skipBack }}s / 快进 {{ skipForward }}s（可在设置里改）
      </span>
    </div>

    <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>

    <!-- 轨道列表（多轨时才有意义） -->
    <div v-if="total > 1" class="mt-4 border-t border-border pt-3">
      <div class="mb-2 text-[11.5px] font-medium text-muted-foreground">共 {{ total }} 轨</div>
      <ol class="max-h-[280px] space-y-0.5 overflow-auto">
        <li v-for="t in tracks" :key="t.index">
          <button
            type="button"
            class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors"
            :class="t.index === index ? 'bg-[var(--shell-accent-tint)] text-primary' : 'text-foreground/90 hover:bg-muted'"
            @click="goto(t.index)"
          >
            <Icon v-if="t.index === index && playing" name="play" class="h-3 w-3 shrink-0" />
            <span v-else class="w-3 shrink-0 text-center text-[10.5px] text-muted-foreground tabular-nums">{{ t.index + 1 }}</span>
            <span class="truncate">{{ t.name }}</span>
          </button>
        </li>
      </ol>
    </div>
  </div>
</template>
