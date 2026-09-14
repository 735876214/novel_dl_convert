<script setup lang="ts">
import { computed } from 'vue'

import Card from '@/components/ui/Card.vue'
import PageHead from '@/components/ui/PageHead.vue'
import Segment from '@/components/ui/Segment.vue'
import SwatchGrid from '@/components/ui/SwatchGrid.vue'
import { ACCENTS } from '@/data/accents'
import { RADIUS_OPTIONS, THEME_LABEL, useThemeStore } from '@/stores/theme'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 设置页：外观（主题 / 点缀色 / 圆角）+ 书源占位。
 * 三项外观设置都直接写 store，store 负责落 localStorage 与 <html> class。
 */
const theme = useThemeStore()
const library = useLibraryStore()
const ui = useUiStore()

const themeOptions = computed(() =>
  (['light', 'dark', 'system'] as const).map((v) => ({ value: v, label: THEME_LABEL[v] })),
)

function onTheme(v: string): void {
  theme.setTheme(v as 'light' | 'dark' | 'system')
  ui.toast(`主题：${THEME_LABEL[v as 'light' | 'dark' | 'system']}`)
}

function onAccent(v: string): void {
  theme.setAccent(v)
}

function onRadius(v: string): void {
  theme.setRadius(v as 'default' | 'sharp' | 'rounded' | 'pill')
  ui.toast('圆角已更新')
}
</script>

<template>
  <div>
    <PageHead title="设置" desc="外观、书源与运行参数" />

    <section class="mb-6">
      <h2 class="mb-3 text-[14px] font-semibold text-foreground">外观</h2>

      <Card padding="none">
        <!-- 主题 -->
        <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-medium text-foreground">主题</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">浅色、深色，或跟随系统</div>
          </div>
          <Segment :options="themeOptions" :model-value="theme.theme" @update:model-value="onTheme" />
        </div>

        <!-- 点缀色 -->
        <div class="border-b border-border px-4 py-3.5">
          <div class="mb-3 flex items-baseline gap-2">
            <span class="text-[13px] font-medium text-foreground">点缀色</span>
            <span class="text-[11.5px] text-muted-foreground">
              共 {{ ACCENTS.length }} 档 · 当前
              {{ ACCENTS.find((a) => a.name === theme.accent)?.label ?? theme.accent }}
            </span>
          </div>
          <SwatchGrid :items="ACCENTS" :model-value="theme.accent" @update:model-value="onAccent" />
        </div>

        <!-- 圆角 -->
        <div class="flex items-center gap-4 px-4 py-3.5">
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-medium text-foreground">圆角</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">全局联动，含卡片、输入框与胶囊</div>
          </div>
          <Segment :options="RADIUS_OPTIONS" :model-value="theme.radius" @update:model-value="onRadius" />
        </div>
      </Card>
    </section>

    <section>
      <div class="mb-3 flex items-baseline gap-2">
        <h2 class="text-[14px] font-semibold text-foreground">书源</h2>
        <span class="text-[11.5px] text-muted-foreground">
          已启用 {{ library.enabledSourceCount }} / {{ library.sources.length }}
        </span>
      </div>

      <Card>
        <div class="flex flex-col gap-2">
          <div
            v-for="s in library.sources"
            :key="s.name"
            class="flex items-center gap-2.5 rounded-md border border-border px-3 py-2"
          >
            <span class="h-2 w-2 shrink-0 rounded-full" :style="{ background: s.on ? s.c1 : 'var(--muted-foreground)' }" />
            <span class="text-[12.5px] font-medium text-foreground">{{ s.name }}</span>
            <span class="text-[11px] text-muted-foreground">{{ s.group }}</span>
            <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">
              成功率 {{ s.rate }}% · {{ s.latency }}ms
            </span>
          </div>
          <p class="mt-1 text-[11.5px] text-muted-foreground">
            书源的注册、批量粘贴与文件上传在「书源管理」页，后续再接入写回。
          </p>
        </div>
      </Card>
    </section>
  </div>
</template>
