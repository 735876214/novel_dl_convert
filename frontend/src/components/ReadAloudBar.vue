<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type ReadAloudInfo } from '@/lib/api'

/**
 * read-along 朗读条（第 188 期）。
 *
 * 只做「句子 ↔ 音频片段」的播放与定位：`<audio>` 的 src 指向服务端按需提取的缓存副本，
 * 每条 cue 用 `clip_begin` / `clip_end` 截取一段。切换句子时通知父组件滚动并高亮正文。
 *
 * 父组件负责正文：本组件只发 `cue` 事件（cue 的 `chapter_index` 由后端按 spine 下标算好）。
 * 位置按 5 秒节流回写 `read_aloud_sync`，暂停 / 卸载时各补一次。
 */
const props = defineProps<{ bookId: string; info: ReadAloudInfo }>()
const emit = defineEmits<{ cue: [index: number]; close: [] }>()

const cues = computed(() => props.info.cues || [])
const idx = ref(0)
const pos = ref(0)
const playing = ref(false)
const err = ref('')
const exportBusy = ref(false)
const audio = ref<HTMLAudioElement | null>(null)
let lastSave = 0

const cue = computed(() => cues.value[idx.value] || null)

function clamp(i: number): number {
  return Math.max(0, Math.min(i, cues.value.length - 1))
}

function urlOf(i: number): string {
  const c = cues.value[i]
  return c ? api.readAloudAudioUrl(props.bookId, c.audio_href) : ''
}

function saveSync(): void {
  const c = cue.value
  if (!c) return
  lastSave = Date.now()
  void api.saveReadAloudSync(props.bookId, idx.value, pos.value).catch(() => {})
}

async function applyCue(i: number, autoplay: boolean): Promise<void> {
  if (!cues.value.length) return
  idx.value = clamp(i)
  const c = cues.value[idx.value]
  pos.value = c.clip_begin
  emit('cue', idx.value)
  await nextTick()
  const a = audio.value
  if (!a) return
  const url = urlOf(idx.value)
  if (a.getAttribute('src') !== url) a.src = url
  try {
    a.currentTime = c.clip_begin
  } catch {
    /* 元数据还没加载完：play 之后再落位 */
  }
  if (autoplay) {
    try {
      await a.play()
      a.currentTime = c.clip_begin
      playing.value = true
    } catch (e) {
      err.value = e instanceof Error ? e.message : '播放失败'
    }
  }
}

function toggle(): void {
  const a = audio.value
  if (!a) return
  if (playing.value) {
    a.pause()
    saveSync()
    return
  }
  void applyCue(idx.value, true)
}

function stop(): void {
  audio.value?.pause()
  playing.value = false
  saveSync()
}

async function exportEpub(): Promise<void> {
  if (exportBusy.value) return
  exportBusy.value = true
  err.value = ''
  try {
    await api.exportReadAloud(props.bookId)
  } catch (e) {
    err.value = e instanceof Error ? e.message : '导出失败'
  } finally {
    exportBusy.value = false
  }
}

function onTime(): void {
  const a = audio.value
  const c = cue.value
  if (!a || !c) return
  pos.value = a.currentTime
  if (a.currentTime >= c.clip_end - 0.02) {
    if (idx.value < cues.value.length - 1) {
      void applyCue(idx.value + 1, true)
    } else {
      a.pause()
      playing.value = false
      saveSync()
    }
    return
  }
  if (Date.now() - lastSave > 5000) saveSync()
}

function onEnded(): void {
  playing.value = false
  if (idx.value < cues.value.length - 1) void applyCue(idx.value + 1, true)
  else saveSync()
}

onMounted(() => {
  const s = props.info.sync
  const start = clamp(Number(s?.cue_index ?? 0))
  pos.value = Number(s?.position_sec ?? 0) || cues.value[start]?.clip_begin || 0
  idx.value = start
  emit('cue', start)
})

onBeforeUnmount(() => {
  audio.value?.pause()
  saveSync()
})
</script>

<template>
  <div class="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/50 px-2.5 py-1.5 text-[11.5px]">
    <Icon name="volume" class="h-3.5 w-3.5 shrink-0 text-primary" />
    <span class="font-medium text-foreground">朗读</span>
    <span class="text-muted-foreground">第 {{ idx + 1 }} / {{ cues.length }} 句</span>
    <span v-if="info.status === 'partial'" class="text-muted-foreground">（{{ info.reason }}）</span>
    <span v-if="err" class="truncate text-destructive">{{ err }}</span>
    <audio
      ref="audio"
      preload="none"
      class="hidden"
      aria-label="朗读音频"
      @timeupdate="onTime"
      @ended="onEnded"
      @play="playing = true"
      @pause="playing = false"
    />

    <div class="ml-auto flex flex-wrap items-center gap-1">
      <Button size="sm" variant="ghost" :disabled="idx <= 0" @click="applyCue(idx - 1, playing)">上一句</Button>
      <Button size="sm" variant="primary" @click="toggle">{{ playing ? '暂停' : '播放' }}</Button>
      <Button size="sm" variant="ghost" :disabled="idx >= cues.length - 1" @click="applyCue(idx + 1, playing)">
        下一句
      </Button>
      <Button size="sm" variant="ghost" @click="stop">停止</Button>
      <Button size="sm" variant="ghost" :disabled="exportBusy" @click="exportEpub">
        {{ exportBusy ? '导出中…' : '导出无音频 EPUB' }}
      </Button>
      <button
        type="button"
        class="cursor-pointer px-1 text-muted-foreground transition-colors hover:text-foreground"
        aria-label="关闭朗读"
        @click="$emit('close')"
      >×</button>
    </div>
  </div>
</template>
