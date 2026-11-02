<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type TtsStatus } from '@/lib/api'

/**
 * TTS 朗读条（第 235 期）。
 *
 * 与 read-along 的朗读条（`ReadAloudBar`）**形态相似、来源不同**：
 * 那一条放的是**书里自带的**媒体叠加（EPUB 的 SMIL），本条放的是**现合成**的音频
 * （自托管 / 局域网的 OpenAI-compatible 引擎）。
 *
 * ⚠️ **只在 TTS 已启用时出现** —— 没启用就不摆「点了没反应」的空条子
 * （本仓纪律：不做假交互）。
 * ⚠️ **合成失败如实说**：显示后端给的中文原因，而不是「没声音」让人猜。
 */
const props = defineProps<{ text: string }>()
const emit = defineEmits<{ close: [] }>()

const status = ref<TtsStatus | null>(null)
/** 后端给的可用性（enabled）。false ⇒ 整条不出现。 */
const enabled = computed(() => Boolean(status.value?.enabled))
const busy = ref(false)
const err = ref('')
const audio = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
/** 合成出来的音频 URL（后端给的缓存地址）。 */
const audioUrl = ref('')
const voice = ref('')

async function load(): Promise<void> {
  try {
    status.value = await api.ttsStatus()
    voice.value = status.value?.voice || ''
  } catch (e) {
    status.value = null
    err.value = e instanceof Error ? e.message : '读不到 TTS 状态'
  }
}

void load()

/** 合成当前段落并播放。失败 ⇒ 如实说原因。 */
async function speak(): Promise<void> {
  const text = props.text.trim()
  if (!text || busy.value) return
  busy.value = true
  err.value = ''
  try {
    const r = await api.ttsSpeak(text, voice.value)
    if (!r.ok) {
      err.value = r.message || '合成失败'
      return
    }
    audioUrl.value = r.url || ''
    await new Promise((r2) => setTimeout(r2, 0))
    const a = audio.value
    if (a && audioUrl.value) {
      a.src = audioUrl.value
      try {
        await a.play()
        playing.value = true
      } catch (e) {
        err.value = e instanceof Error ? e.message : '播放失败'
      }
    }
  } catch (e) {
    err.value = e instanceof Error ? e.message : '合成失败'
  } finally {
    busy.value = false
  }
}

function stop(): void {
  const a = audio.value
  if (a) {
    a.pause()
    playing.value = false
  }
}

function onEnded(): void {
  playing.value = false
}

onBeforeUnmount(stop)
</script>

<template>
  <div
    v-if="enabled"
    class="flex flex-wrap items-center gap-2 rounded-md border border-border bg-card px-3 py-2"
  >
    <Icon name="volume" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
    <span class="text-[12px] font-medium text-foreground">朗读（TTS）</span>
    <span class="text-[11.5px] text-muted-foreground">
      由自托管语音服务合成 · 音色
      <input
        v-model="voice"
        type="text"
        aria-label="TTS 音色"
        placeholder="alloy"
        class="ml-1 h-6 w-20 rounded border border-border bg-muted px-1.5 font-mono text-[11px] text-foreground outline-none focus:border-ring"
      >
    </span>
    <Button size="sm" variant="primary" :disabled="busy || !text.trim()" @click="speak">
      {{ busy ? '合成中…' : '朗读本段' }}
    </Button>
    <Button v-if="playing" size="sm" variant="ghost" @click="stop">停止</Button>
    <span v-if="err" class="text-[11.5px] text-destructive">{{ err }}</span>
    <Button size="sm" variant="ghost" class="ml-auto" title="关闭" @click="emit('close')">
      <Icon name="x" class="h-3.5 w-3.5" />
    </Button>
    <audio
      ref="audio"
      class="hidden"
      preload="none"
      @ended="onEnded"
    />
  </div>
</template>
