<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  AUDIO_PREFS_DEFAULT,
  AUDIO_SKIP_BACKS,
  AUDIO_SKIP_FORWARDS,
  AUDIO_SLEEPS,
  AUDIO_SPEEDS,
  readAudioPrefs,
  saveAudioPrefs,
  type AudioPrefs,
} from '@/lib/audioPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Reader → Audiobook（`/settings/reader/audio`）
 *
 * 真实实现（与播放器共享 localStorage 的 `audio-prefs`）：
 *   默认倍速、默认音量、快退间隔、快进间隔、睡眠定时默认时长。
 * 这些是**默认值**：播放器里改倍速只影响当次播放，不改这里的默认。
 */
const ui = useUiStore()
const prefs = ref<AudioPrefs>(readAudioPrefs())

function persist(): void {
  saveAudioPrefs(prefs.value)
}

function reset(): void {
  prefs.value = { ...AUDIO_PREFS_DEFAULT }
  persist()
  ui.toast('已恢复默认有声书偏好')
}

const ROW = 'flex items-center gap-4 border-b border-border px-4 py-3.5'
const LABEL = 'w-24 shrink-0 text-[13px] font-medium text-foreground'
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">有声书</h2>
      <span class="text-[11.5px] text-muted-foreground">播放器默认值：倍速 / 音量 / 跳转间隔 / 睡眠定时</span>
      <Button size="sm" class="ml-auto" @click="reset">恢复默认</Button>
    </div>

    <Card padding="none">
      <div :class="ROW">
        <div :class="LABEL">默认倍速</div>
        <div class="flex flex-1 flex-wrap gap-1.5">
          <button
            v-for="s in AUDIO_SPEEDS"
            :key="s"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.speed === s ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.speed = s; persist()"
          >
            {{ s }}x
          </button>
        </div>
      </div>

      <div :class="ROW">
        <div :class="LABEL">默认音量</div>
        <div class="flex flex-1 items-center gap-3">
          <input
            v-model.number="prefs.volume"
            type="range" min="0" max="1" step="0.05"
            class="w-56 cursor-pointer accent-primary"
            @change="persist"
          >
          <span class="text-[12px] text-muted-foreground tabular-nums">{{ Math.round(prefs.volume * 100) }}%</span>
        </div>
      </div>

      <div :class="ROW">
        <div :class="LABEL">快退间隔</div>
        <div class="flex flex-1 flex-wrap gap-1.5">
          <button
            v-for="s in AUDIO_SKIP_BACKS"
            :key="s"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.skipBack === s ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.skipBack = s; persist()"
          >
            {{ s }} 秒
          </button>
        </div>
      </div>

      <div :class="ROW">
        <div :class="LABEL">快进间隔</div>
        <div class="flex flex-1 flex-wrap gap-1.5">
          <button
            v-for="s in AUDIO_SKIP_FORWARDS"
            :key="s"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.skipForward === s ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.skipForward = s; persist()"
          >
            {{ s }} 秒
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 px-4 py-3.5">
        <div :class="LABEL">睡眠定时</div>
        <div class="flex flex-1 flex-wrap gap-1.5">
          <button
            v-for="m in AUDIO_SLEEPS"
            :key="m"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.sleepMinutes === m ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.sleepMinutes = m; persist()"
          >
            {{ m ? `${m} 分钟` : '关闭' }}
          </button>
        </div>
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
      这些是**默认值**：播放器里临时调倍速只影响当次播放；睡眠定时到点会自动暂停并在播放器里提示。
      有声书支持「一个目录 = 一本书」（一章一文件）与单个音频文件两种形态，播放进度按秒保存并跨设备同步。
    </p>
  </div>
</template>
