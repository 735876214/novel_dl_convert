<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import Card from '@/components/ui/Card.vue'
import Segment from '@/components/ui/Segment.vue'
import SwatchGrid from '@/components/ui/SwatchGrid.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { ACCENTS } from '@/data/accents'
import { RADIUS_OPTIONS, TEXTURE_OPTIONS, THEME_LABEL, useThemeStore } from '@/stores/theme'
import { useCustomIconsStore } from '@/stores/customIcons'
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
const customIcons = useCustomIconsStore()
const iconName = ref('')
const iconSvg = ref('')
const iconBusy = ref(false)
const iconError = ref('')

onMounted(() => void customIcons.load())

async function addIcon(): Promise<void> {
  if (iconBusy.value || !iconName.value.trim() || !iconSvg.value.trim()) return
  iconBusy.value = true
  iconError.value = ''
  try {
    const it = await customIcons.create(iconName.value.trim(), iconSvg.value)
    iconName.value = ''
    iconSvg.value = ''
    ui.toast(`图标「${it.name}」已添加`)
  } catch (e) {
    iconError.value = e instanceof Error ? e.message : '添加图标失败'
  } finally {
    iconBusy.value = false
  }
}

async function removeIcon(key: string): Promise<void> {
  try {
    await customIcons.remove(key)
    ui.toast('图标已删除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

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

/** 背景纹理（第 227 期）：换档即换 `<html>` 上的 `texture-<key>` class。 */
function onTexture(v: string): void {
  theme.setTexture(v)
  ui.toast('背景纹理已更新')
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
          <div class="text-[13px] font-medium text-foreground">背景纹理</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            共 {{ TEXTURE_OPTIONS.length }} 档 · 纯 CSS 绘制，不引图片、不出网；
            纹理很淡，不影响正文对比度
          </div>
        </div>
        <Segment :options="TEXTURE_OPTIONS" :model-value="theme.texture" @update:model-value="onTexture" />
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

    <!-- 自定义图标（第 216 期）：只收 SVG 的 path d；按钮/库图标选择器都能选 -->
    <Card class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="text-[13px] font-medium text-foreground">自定义图标</div>
        <div class="mt-0.5 text-[11.5px] text-muted-foreground">
          粘贴 SVG（只提取 &lt;path d&gt;，不保留脚本 / 外链），添加后可在书库图标里选用
        </div>
      </div>
      <div v-if="customIcons.items.length" class="flex flex-wrap gap-2 border-b border-border px-4 py-3">
        <div
          v-for="it in customIcons.items"
          :key="it.key"
          class="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-[11.5px]"
        >
          <Icon :name="it.key" class="h-4 w-4 text-foreground" />
          <span class="max-w-28 truncate text-muted-foreground">{{ it.name }}</span>
          <button
            type="button"
            class="cursor-pointer text-[11px] text-destructive hover:underline"
            @click="removeIcon(it.key)"
          >删除</button>
        </div>
      </div>
      <div v-else class="border-b border-border px-4 py-3 text-[11.5px] text-muted-foreground">
        还没有自定义图标。
      </div>
      <div class="flex flex-wrap items-end gap-2 px-4 py-3">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">名称</span>
          <input
            v-model="iconName"
            aria-label="图标名称"
            class="h-7 w-32 rounded-md border border-border bg-card px-1.5 text-[11.5px] text-foreground outline-none focus:border-ring"
          >
        </label>
        <label class="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">SVG 源码</span>
          <textarea
            v-model="iconSvg"
            aria-label="图标 SVG"
            rows="3"
            placeholder="<svg viewBox='0 0 24 24'><path d='…'/></svg>"
            class="rounded-md border border-border bg-card px-1.5 py-1 font-mono text-[11px] text-foreground outline-none focus:border-ring"
          />
        </label>
        <Button size="sm" variant="primary" :disabled="iconBusy || !iconName.trim() || !iconSvg.trim()" @click="addIcon">
          {{ iconBusy ? '添加中…' : '添加图标' }}
        </Button>
      </div>
      <p v-if="iconError" class="px-4 pb-3 text-[11.5px] text-destructive">{{ iconError }}</p>
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
