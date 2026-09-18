<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  PDF_FITS,
  PDF_PREFS_DEFAULT,
  PDF_RANGES,
  PDF_SCROLL_MODES,
  PDF_SPREADS,
  readPdfPrefs,
  savePdfPrefs,
  type PdfPrefs,
} from '@/lib/pdfPrefs'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * YOU → Reader → PDF（`/settings/reader/pdf`）
 *
 * 真实实现（与 PDF 阅读器共享 localStorage 的 `pdf-prefs`）：
 *   滚动模式（翻页 / 纵向 / 横向）、页展（单页 / 双页奇右 / 偶右 / 自动）、
 *   适配方式（整页 / 适配宽度 / 自动 / 自定义）、自定义缩放。
 * 未支持：页与页之间的自定义间距。
 */
const ui = useUiStore()
const prefs = ref<PdfPrefs>(readPdfPrefs())

function persist(): void {
  savePdfPrefs(prefs.value)
}

function reset(): void {
  prefs.value = { ...PDF_PREFS_DEFAULT }
  persist()
  ui.toast('已恢复默认 PDF 偏好')
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">PDF</h2>
      <span class="text-[11.5px] text-muted-foreground">PDF 阅读器的默认呈现方式</span>
      <Button size="sm" class="ml-auto" @click="reset">恢复默认</Button>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">滚动模式</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="m in PDF_SCROLL_MODES"
            :key="m.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.scrollMode === m.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.scrollMode = m.key; persist()"
          >
            {{ m.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">页展</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="s in PDF_SPREADS"
            :key="s.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.spread === s.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.spread = s.key; persist()"
          >
            {{ s.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">适配方式</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="f in PDF_FITS"
            :key="f.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.fit === f.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.fit = f.key; persist()"
          >
            {{ f.label }}
          </button>
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-2 flex items-baseline justify-between">
          <span class="text-[13px] font-medium text-foreground">自定义缩放</span>
          <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ prefs.zoom.toFixed(2) }}{{ PDF_RANGES.zoom.unit }}</span>
        </div>
        <input
          type="range"
          class="w-full"
          :min="PDF_RANGES.zoom.min"
          :max="PDF_RANGES.zoom.max"
          :step="PDF_RANGES.zoom.step"
          :value="prefs.zoom"
          @input="prefs.zoom = ($event.target as HTMLInputElement).valueAsNumber; prefs.fit = 'custom'; persist()"
        >
        <p class="mt-1 text-[11.5px] text-muted-foreground">拖动即切到「自定义」适配；「适配宽度 / 整页」会忽略这个值。</p>
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] text-muted-foreground">
      说明：PDF 由 pdf.js 渲染。渲染器采用<strong>懒加载</strong>——只有打开 PDF 时才下载（约 117 KB + 291 KB gzip），
      不影响书架与 EPUB 阅读器的加载体积。
    </p>

    <SettingsUnsupportedCard
      label="PDF"
      :groups="['LAYOUT', 'ZOOM']"
      :items="['页与页之间的自定义间距（Spread gap）']"
      note="本项目已实现：滚动模式 / 页展 / 适配方式 / 自定义缩放 / 阅读进度记录。"
    />
  </div>
</template>
