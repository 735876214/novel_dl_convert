<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import {
  READER_FONTS,
  READER_MODES,
  READER_PREFS_DEFAULT,
  READER_RANGES,
  READER_THEMES,
  readReaderPrefs,
  saveReaderPrefs,
  type ReaderPrefs,
} from '@/lib/readerPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Reader → eBook（`/settings/reader/ebook`）
 *
 * 真实实现（与阅读器共享同一份 localStorage 偏好）：
 *   阅读模式（滚动/翻页）、13 档主题、字体、字号、行高、内容宽度、
 *   段落间距、首行缩进、字距、词距、分栏、两端对齐、断词。
 * 未支持：新书套用设置、固定版式页宽、字重样式、文本区左右内边距。
 */

const ui = useUiStore()
const prefs = ref<ReaderPrefs>(readReaderPrefs())

function persistPrefs(): void {
  saveReaderPrefs(prefs.value)
}

function resetReader(): void {
  prefs.value = { ...READER_PREFS_DEFAULT }
  persistPrefs()
  ui.toast('已恢复默认阅读偏好')
}

// 滑杆由配置数组驱动：新增一项只需加一行
type NumPrefKey = keyof typeof READER_RANGES
const SLIDERS = (
  [
    ['size', '字号', 0],
    ['lineHeight', '行高', 1],
    ['paragraphSpacing', '段落间距', 1],
    ['indent', '首行缩进', 1],
    ['letterSpacing', '字距', 2],
    ['wordSpacing', '词距', 2],
    ['width', '内容宽度', 0],
    ['columns', '分栏（仅翻页模式生效）', 0],
  ] as Array<[NumPrefKey, string, number]>
).map(([key, label, digits]) => ({ key, label, digits, ...READER_RANGES[key] }))

function setNum(key: NumPrefKey, value: number): void {
  if (!Number.isFinite(value)) return
  ;(prefs.value as unknown as Record<string, number>)[key] = value
  persistPrefs()
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">电子书</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">eBook</span>
      <span class="text-[11.5px] text-muted-foreground">阅读器打开时使用的默认排版</span>
      <Button size="sm" class="ml-auto" @click="resetReader">恢复默认</Button>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">阅读模式</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="m in READER_MODES"
            :key="m.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.mode === m.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.mode = m.key; persistPrefs()"
          >
            {{ m.label }}
          </button>
        </div>
      </div>

      <div class="flex items-start gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 pt-1 text-[13px] font-medium text-foreground">阅读主题</div>
        <div class="grid flex-1 grid-cols-4 gap-1.5 sm:grid-cols-7">
          <button
            v-for="t in READER_THEMES"
            :key="t.key"
            type="button"
            class="cursor-pointer rounded-md border px-1 py-2 text-[11px] leading-tight transition-colors"
            :class="prefs.theme === t.key ? 'border-ring font-medium' : 'border-border/70'"
            :style="{ background: t.bg, color: t.fg }"
            :title="t.label"
            @click="prefs.theme = t.key; persistPrefs()"
          >
            {{ t.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">字体</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="f in READER_FONTS"
            :key="f.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.font === f.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.font = f.key; persistPrefs()"
          >
            {{ f.label }}
          </button>
        </div>
      </div>

      <div
        v-for="(s, i) in SLIDERS"
        :key="s.key"
        class="px-4 py-3.5"
        :class="i < SLIDERS.length - 1 ? 'border-b border-border' : ''"
      >
        <div class="mb-2 flex items-baseline justify-between">
          <span class="text-[13px] font-medium text-foreground">{{ s.label }}</span>
          <span class="text-[11.5px] text-muted-foreground tabular-nums">
            {{ s.key === 'columns' ? `${prefs.columns} 栏` : `${prefs[s.key].toFixed(s.digits)}${s.unit}` }}
          </span>
        </div>
        <input
          type="range"
          class="w-full"
          :min="s.min"
          :max="s.max"
          :step="s.step"
          :value="prefs[s.key]"
          @input="setNum(s.key, ($event.target as HTMLInputElement).valueAsNumber)"
        >
      </div>

      <div class="flex items-center gap-8 border-t border-border px-4 py-3.5">
        <label class="flex cursor-pointer items-center gap-2 text-[13px] text-foreground">
          <input v-model="prefs.justify" type="checkbox" class="accent-[var(--primary)]" @change="persistPrefs">
          <span>两端对齐</span>
        </label>
        <label class="flex cursor-pointer items-center gap-2 text-[13px] text-foreground">
          <input v-model="prefs.hyphens" type="checkbox" class="accent-[var(--primary)]" @change="persistPrefs">
          <span>断词（西文长词换行）</span>
        </label>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="eBook"
      :groups="['NEW BOOKS', 'ADVANCED']"
      :items="[
        'Apply my settings to new books（新书是否套用我的设置）',
        'Fixed-layout page spreads（Book default / Single page / Columns）',
        'Font style（Regular / Bold / Regular Italic / Bold Italic）',
        'Column gap（文本区左右内边距）',
      ]"
      note="本项目已实现「阅读模式 / 13 档主题 / 字体 / 字号 / 行高 / 内容宽度 / 段落间距 / 首行缩进 / 字距 / 词距 / 分栏 / 两端对齐 / 断词」共 13 项；其余为未支持。"
    />
  </div>
</template>
