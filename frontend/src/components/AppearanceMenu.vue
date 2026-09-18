<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
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

const ICON_BTN =
  'grid h-[2.0625rem] w-[2.0625rem] cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'

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
    <button
      :class="[ICON_BTN, open ? 'bg-[var(--shell-accent-tint)] text-primary hover:text-primary' : '']"
      type="button"
      :title="`外观（当前：${THEME_LABEL[theme.theme]}）`"
      aria-label="外观"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="1.7"
        stroke-linecap="round"
        stroke-linejoin="round"
        class="h-[17px] w-[17px]"
      >
        <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
      </svg>
    </button>

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
