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
  COMIC_SPREAD_ALIGNS,
  COMIC_WIDE_PAGES,
  readComicPrefs,
  saveComicPrefs,
  type ComicPrefs,
} from '@/lib/comicPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Reader → Comics（`/settings/reader/comics`）
 *
 * 真实实现（与漫画阅读器共享 localStorage 的 `comic-prefs`）：
 *   阅读模式（翻页 / 纵向连续 / **纵向连续无间隙**）、页视图（单页 / 双页）、
 *   适配（整页 / 宽 / 高 / 原始）、阅读方向（左→右 / 右→左）、页间距、背景色，
 *   以及第 51 期补齐的**跨页对齐、宽页处理、小屏强制双页、自动翻到下一本**。
 * 上游该页 6 组 10 项至此**全部覆盖**，故页尾不再有「未支持」对照卡。
 *
 * 支持 CBZ 与 CBR：CBR 由服务端的 zip/rar 双后端解压（依赖 bsdtar，容器内由 libarchive-tools 提供）。
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
      <span class="text-[11.5px] text-muted-foreground">漫画（CBZ / CBR）阅读器的默认呈现方式</span>
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

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-24 shrink-0 text-[13px] font-medium text-foreground">跨页对齐</div>
        <div class="flex flex-1 gap-1.5">
          <button
            v-for="s in COMIC_SPREAD_ALIGNS"
            :key="s.key"
            type="button"
            class="flex-1 cursor-pointer rounded-md border px-2 py-1.5 text-[12px] transition-colors"
            :class="prefs.spreadAlign === s.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.spreadAlign = s.key; persist()"
          >
            {{ s.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">宽页处理</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            双页模式下遇到跨页大图时：照常并排会把它和邻页一起挤扁，可改为单独占一屏
          </div>
        </div>
        <div class="flex shrink-0 gap-1.5">
          <button
            v-for="w in COMIC_WIDE_PAGES"
            :key="w.key"
            type="button"
            class="cursor-pointer rounded-md border px-3 py-1.5 text-[12px] transition-colors"
            :class="prefs.widePage === w.key ? 'border-ring font-medium text-foreground' : 'border-border text-muted-foreground hover:text-foreground'"
            @click="prefs.widePage = w.key; persist()"
          >
            {{ w.label }}
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">小屏强制双页</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启时双页与屏幕宽度无关（默认，与加这项之前一致）；关掉后窄屏自动回落单页
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="prefs.forceTwoPage"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="prefs.forceTwoPage ? 'bg-primary' : 'bg-muted'"
          @click="prefs.forceTwoPage = !prefs.forceTwoPage; persist()"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="prefs.forceTwoPage ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">自动翻到下一本</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            读到末页（或连续模式滚到底）后，按系列序号自动打开下一册；
            无系列、已是最后一册时只提示、不跳转
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="prefs.autoNext"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="prefs.autoNext ? 'bg-primary' : 'bg-muted'"
          @click="prefs.autoNext = !prefs.autoNext; persist()"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="prefs.autoNext ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
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
      说明：漫画支持 <span class="text-foreground">CBZ</span>（zip）与 <span class="text-foreground">CBR</span>（RAR）。
      CBR 由服务端的 zip/rar 双后端解压，依赖系统解压器 <code class="font-mono">bsdtar</code>
      （容器内由 <code class="font-mono">libarchive-tools</code> 提供，macOS 自带）；缺依赖时接口会明确返回 503。
      页图按需加载，不会一次拉整本。
    </p>

  </div>
</template>
