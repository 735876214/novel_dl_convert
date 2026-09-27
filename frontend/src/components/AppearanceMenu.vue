<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import IconButton from '@/components/ui/IconButton.vue'
import Segment from '@/components/ui/Segment.vue'
import SwatchGrid from '@/components/ui/SwatchGrid.vue'
import { ACCENTS } from '@/data/accents'
import { RADIUS_OPTIONS, THEME_LABEL, useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'

/**
 * 顶栏外观快捷浮层（对应上游顶栏的 Appearance 浮层）。
 *
 * 三种外观维度（主题 / 点缀色 / 圆角）复用与「设置 → 外观 → 主题」完全相同的
 * Segment / SwatchGrid 组件与 theme store 入口，保证浮层与整页设置行为一致、
 * 零重复逻辑。点击外部 / Esc 关闭，沿用 NotificationBell 的模式。
 */
const theme = useThemeStore()
const ui = useUiStore()
const router = useRouter()

const open = ref(false)
const wrap = ref<HTMLElement | null>(null)

const themeOptions = computed(() =>
  (['light', 'dark', 'system'] as const).map((v) => ({ value: v, label: THEME_LABEL[v] })),
)

function toggle(): void {
  open.value = !open.value
}

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

function goFull(): void {
  open.value = false
  router.push('/settings/appearance/theme')
}

function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  const t = e.target as Node
  if (wrap.value && !wrap.value.contains(t)) open.value = false
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="wrap" class="relative">
    <!-- 第 65 期起改用 `ui/IconButton`（圆形描边 + 气泡 + 角标三件事收在一处定义）。
         原先这里内联的月亮 path 换成 `lib/icons.ts` 里已有的 `moon`：语义相同（都是
         新月），少一份永不更新的复制。原生 `title` 一并去掉 —— 有了自绘气泡，
         两个提示会一起冒出来（无障碍信息由 IconButton 的 `aria-label` 承担）。 -->
    <IconButton
      label="外观"
      :tooltip="`外观（当前：${THEME_LABEL[theme.theme]}）`"
      :active="open"
      :expanded="open"
      @click.stop="toggle"
    >
      <Icon name="moon" class="h-[17px] w-[17px]" />
    </IconButton>

    <!-- 浮层：点按钮切换，点外部 / Esc 关闭 -->
    <div
      v-if="open"
      class="absolute top-[calc(100%+0.5rem)] right-0 z-50 w-[min(23rem,92vw)] overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-2xl backdrop-blur-md backdrop-saturate-150"
    >
      <div class="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
        <h3 class="text-[13px] font-semibold text-foreground">外观</h3>
        <span class="text-[11px] text-muted-foreground">主题 · 点缀色 · 圆角</span>
        <Button size="sm" variant="ghost" class="ml-auto" @click.stop="goFull">完整设置</Button>
      </div>

      <div class="max-h-[min(26rem,64vh)] space-y-4 overflow-y-auto px-3.5 py-3.5">
        <div class="flex items-center gap-4">
          <span class="w-12 shrink-0 text-[13px] font-medium text-foreground">主题</span>
          <Segment :options="themeOptions" :model-value="theme.theme" @update:model-value="onTheme" />
        </div>

        <div>
          <div class="mb-2 flex items-baseline gap-2">
            <span class="text-[13px] font-medium text-foreground">点缀色</span>
            <span class="text-[11px] text-muted-foreground">
              共 {{ ACCENTS.length }} 档 · {{ ACCENTS.find((a) => a.name === theme.accent)?.label ?? theme.accent }}
            </span>
          </div>
          <SwatchGrid :items="ACCENTS" :model-value="theme.accent" @update:model-value="onAccent" />
        </div>

        <div class="flex items-center gap-4">
          <span class="w-12 shrink-0 text-[13px] font-medium text-foreground">圆角</span>
          <Segment :options="RADIUS_OPTIONS" :model-value="theme.radius" @update:model-value="onRadius" />
        </div>
      </div>

      <div class="border-t border-border p-2">
        <Button variant="ghost" block @click.stop="resetAppearance">恢复默认外观</Button>
      </div>
    </div>
  </div>
</template>
