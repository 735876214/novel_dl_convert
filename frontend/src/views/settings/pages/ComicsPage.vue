<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  COMIC_BGS,
  COMIC_DIRECTIONS,
  COMIC_FITS,
  COMIC_MODES,
  COMIC_PAGE_VIEWS,
  COMIC_PREFS_DEFAULT,
  COMIC_RANGES,
  readComicPrefs,
  saveComicPrefs,
  type ComicPrefs,
} from '@/lib/comicPrefs'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * YOU → Reader → Comics（`/settings/reader/comics`）
 *
 * 真实实现（与漫画阅读器共享 localStorage 的 `comic-prefs`）：
 *   阅读模式（翻页 / 纵向连续）、页视图（单页 / 双页）、适配（整页 / 宽 / 高 / 原始）、
 *   阅读方向（左→右 / 右→左）、页间距、背景色。
 * 未支持：跨页对齐、宽页单独处理、小屏强制双页、自动翻下一本。
 *
 * 只支持 CBZ；CBR（RAR）需要额外解压依赖，本项目不做。
 */
const ui = useUiStore()
const prefs = ref<ComicPrefs>(readComicPrefs())

function persist(): void {
  saveComicPrefs(prefs.value)
}

function reset(): void {
  prefs.value = { ...COMIC_PREFS_DEFAULT }
  persist()
  ui.toast('已恢复默认漫画偏好')
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">漫画</h2>
      <span class="text-[11.5px] text-muted-foreground">CBZ 阅读器的默认呈现方式</span>
      <Button size="sm" class="ml-auto" @click="reset">恢复默认</Button>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">阅读模式</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="m in COMIC_MODES"
            :key="m.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.mode === m.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.mode = m.key; persist()"
          >
            {{ m.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">页视图</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="v in COMIC_PAGE_VIEWS"
            :key="v.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.pageView === v.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.pageView = v.key; persist()"
          >
            {{ v.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">适配方式</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="f in COMIC_FITS"
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

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">阅读方向</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="d in COMIC_DIRECTIONS"
            :key="d.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.direction === d.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.direction = d.key; persist()"
          >
            {{ d.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">背景色</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="b in COMIC_BGS"
            :key="b.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.bg === b.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.bg = b.key; persist()"
          >
            {{ b.label }}
          </button>
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-2 flex items-baseline justify-between">
          <span class="text-[13px] font-medium text-foreground">页间距</span>
          <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ prefs.gap }}{{ COMIC_RANGES.gap.unit }}</span>
        </div>
        <input
          type="range"
          class="w-full"
          :min="COMIC_RANGES.gap.min"
          :max="COMIC_RANGES.gap.max"
          :step="COMIC_RANGES.gap.step"
          :value="prefs.gap"
          @input="prefs.gap = ($event.target as HTMLInputElement).valueAsNumber; persist()"
        >
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] text-muted-foreground">
      说明：漫画支持 <span class="text-foreground">CBZ</span>（zip 打包的图片）。
      CBR 是 RAR 格式，需要额外的系统级解压依赖，本项目不做 —— 放一本打不开的书进书架比不显示更糟。
      页图按需加载，不会一次拉整本。
    </p>

    <SettingsUnsupportedCard
      label="Comics"
      :groups="['VIEW', 'DISPLAY']"
      :items="[
        '跨页对齐（Spread alignment）',
        '宽页单独处理（Wide-page handling）',
        '小屏强制双页（Force two-page on small screens）',
        '自动翻到下一本（Auto-advance to next book）',
        'CBR 支持（需 RAR 解压依赖）',
      ]"
      note="本项目已实现：阅读模式 / 页视图 / 适配方式 / 阅读方向（含日漫右→左）/ 页间距 / 背景色 / 阅读进度。"
    />
  </div>
</template>
