<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Segment from '@/components/ui/Segment.vue'
import SwatchGrid from '@/components/ui/SwatchGrid.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { ACCENTS } from '@/data/accents'
import { RADIUS_OPTIONS, THEME_LABEL, useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Display → Theme（`/settings/appearance/theme`）
 *
 * 真实实现：主题 / 点缀色 / 圆角；「保存位置」由「偏好与同步」页统管
 * （外观与阅读偏好作为**一个整体**同步，不做分类单独选择 —— 见该页说明）。
 * 未支持：「背景图案」。
 */

const theme = useThemeStore()
const ui = useUiStore()
const router = useRouter()

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

function resetAppearance(): void {
  theme.setTheme('system')
  theme.setAccent('neutral')
  theme.setRadius('default')
  ui.toast('已恢复默认外观')
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">主题</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Theme</span>
      <Button size="sm" class="ml-auto" @click="resetAppearance">恢复默认外观</Button>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">主题</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">浅色、深色，或跟随系统</div>
        </div>
        <Segment :options="themeOptions" :model-value="theme.theme" @update:model-value="onTheme" />
      </div>

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

      <div class="flex items-center gap-4 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">圆角</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">全局联动，含卡片、输入框与胶囊</div>
        </div>
        <Segment :options="RADIUS_OPTIONS" :model-value="theme.radius" @update:model-value="onRadius" />
      </div>

      <div class="flex items-center gap-4 border-t border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">保存位置</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            本机 / 账号由「偏好与同步」统管：外观与阅读偏好作为一整套，可按设备各用各的
          </div>
        </div>
        <Button size="sm" @click="router.push('/settings/reader/general')">偏好与同步</Button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="Theme"
      :groups="['LIBRARY BACKGROUND']"
      :items="[
        'Background pattern：20 个图案（None / Dots / Cross / Blueprint / Aurora / Prism / Eclipse 等）',
        'Surface opacity：界面不透明度滑杆（上游只在顶栏快捷面板提供）',
        '按偏好分类单独选择保存位置（本项目把阅读 + 外观作为一整套同步）',
      ]"
      note="外观设置存浏览器本地存储，作为首屏与离线来源；配合「偏好与同步」可存成模式、在多设备间套用，或让每台设备各用各的。背景图案与界面不透明度未实现。"
    />
  </div>
</template>
