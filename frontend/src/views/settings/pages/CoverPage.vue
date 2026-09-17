<script setup lang="ts">
import { computed, onMounted } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import BookCover from '@/components/ui/BookCover.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { findSettingsPage } from '@/data/settingsNav'
import { useCoverPrefsStore, COVER_DISPLAY_OPTIONS, COVER_SHADOW_OPTIONS, COVER_SPINE_OPTIONS, COVER_OVERLAY_OPTIONS } from '@/stores/coverPrefs'
import { useLibraryStore } from '@/stores/library'

/**
 * YOU → Display → Book Covers（`/settings/appearance/book-covers`）
 *
 * 偏好存 localStorage（`stores/coverPrefs`），**改完立即生效、没有保存按钮** ——
 * 与「主题」一致：本项目的「外观」类偏好都在前端，不存在服务端写入，
 * 放一个保存按钮反而会让人以为不点就不生效。
 *
 * 未支持：封面搜索提供者（依赖在线封面抓取）、漫画是否显示书脊（本项目无漫画支持）、
 * 详情页封面取色（需要详情页配合，未做）。
 */
const prefs = useCoverPrefsStore()
const library = useLibraryStore()

const upstream = computed(() => findSettingsPage('appearance/book-covers')?.upstream)

/** 用真实书目做预览；优先选有封面的，让三种显示方式的差异看得出来 */
const preview = computed(() => {
  const bs = library.books
  const withCover = bs.filter((b) => b.has_cover)
  const rest = bs.filter((b) => !b.has_cover)
  return [...withCover, ...rest].slice(0, 3)
})

const unsupportedItems = computed(() =>
  (upstream.value?.items ?? []).filter((i) => !IMPLEMENTED.some((k) => i.startsWith(k))),
)

/** 已实现的条目不在「未支持」卡片里重复出现（前缀匹配上游原文） */
const IMPLEMENTED = ['Cover display mode', 'Book spine overlay', 'Cover shadow strength', 'Card overlays']

onMounted(() => {
  void library.loadBooks()
})

function chip(active: boolean): string {
  return active
    ? 'bg-primary text-primary-foreground'
    : 'bg-muted text-muted-foreground hover:text-foreground'
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">封面样式</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Book Covers</span>
      <Badge tone="accent">部分实现</Badge>
      <span class="text-[11.5px] text-muted-foreground">改动立即生效（存本机）</span>
      <Button size="sm" class="ml-auto" @click="prefs.reset()">恢复默认</Button>
    </div>
    <p v-if="upstream?.desc" class="mb-3 font-mono text-[11px] text-muted-foreground">
      {{ upstream.desc }}
    </p>

    <!-- 预览：真书目 + 真实偏好，改上面动下面 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">预览</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          取自真实书目，随下方设置即时变化。没有内嵌封面的书会显示渐变占位。
        </p>
      </div>
      <div class="grid grid-cols-3 gap-4 px-4 py-4 sm:grid-cols-4">
        <div v-for="b in preview" :key="b.id">
          <BookCover :book="b" :show-title="true" />
          <div class="mt-1.5 truncate text-[11.5px] text-foreground">{{ b.title || b.name }}</div>
        </div>
      </div>
    </Card>

    <!-- 显示方式 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">封面填充方式</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          「填满卡片」「自然比例贴底」用照搬来的封面效果 CSS；<strong>「模糊底图」是本项目自己实现的</strong>
          （上游那份 CSS 没有对应类）。
        </p>
      </div>
      <div class="flex flex-col gap-2 px-4 py-3">
        <button
          v-for="o in COVER_DISPLAY_OPTIONS"
          :key="o.value"
          type="button"
          class="flex cursor-pointer items-start gap-3 rounded-md border border-border px-3 py-2 text-left transition-colors"
          :class="prefs.prefs.display === o.value ? 'border-primary bg-primary/6' : 'hover:bg-muted'"
          @click="prefs.patch({ display: o.value })"
        >
          <span
            class="mt-1 h-3 w-3 shrink-0 rounded-full border"
            :class="prefs.prefs.display === o.value ? 'border-primary bg-primary' : 'border-border'"
          />
          <span class="min-w-0">
            <span class="block text-[12.5px] font-medium text-foreground">{{ o.label }}</span>
            <span class="block text-[11.5px] text-muted-foreground">{{ o.hint }}</span>
          </span>
        </button>
      </div>
    </Card>

    <!-- 书脊 + 阴影 -->
    <Card padding="none" class="mb-4">
      <div v-for="(row, idx) in [
        { key: 'spine', label: '书脊效果', opts: COVER_SPINE_OPTIONS, hint: '覆盖在封面左缘的一道渐变，模拟书脊' },
        { key: 'shadow', label: '阴影强度', opts: COVER_SHADOW_OPTIONS, hint: 'CSS 只提供默认 / 加强两档，「关闭」由前端覆盖变量实现' },
      ]" :key="row.key" :class="idx ? 'border-t border-border' : ''">
        <div class="px-4 py-3">
          <div class="flex flex-wrap items-center gap-3">
            <div class="min-w-0 flex-1">
              <div class="text-[12.5px] font-medium text-foreground">{{ row.label }}</div>
              <div class="mt-0.5 text-[11.5px] text-muted-foreground">{{ row.hint }}</div>
            </div>
            <div class="flex shrink-0 gap-1.5">
              <button
                v-for="o in row.opts"
                :key="o.value"
                type="button"
                class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
                :class="chip(prefs.prefs[row.key as 'spine' | 'shadow'] === o.value)"
                @click="prefs.patch({ [row.key]: o.value } as never)"
              >
                {{ o.label }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Card>

    <!-- 卡片叠加层 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">卡片叠加层</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          全部默认关闭：书架本来就在封面下方显示进度，默认再叠一层会成为重复信息。
        </p>
      </div>
      <div class="grid grid-cols-1 gap-x-6 px-4 py-2 sm:grid-cols-2">
        <button
          v-for="o in COVER_OVERLAY_OPTIONS"
          :key="o.value"
          type="button"
          class="flex cursor-pointer items-center gap-3 border-b border-border/60 py-2.5 text-left last:border-b-0"
          @click="prefs.toggleOverlay(o.value)"
        >
          <span
            class="grid h-4 w-4 shrink-0 place-items-center rounded border text-[10px]"
            :class="prefs.prefs.overlays.includes(o.value) ? 'border-primary bg-primary text-primary-foreground' : 'border-border'"
          >
            <span v-if="prefs.prefs.overlays.includes(o.value)">✓</span>
          </span>
          <span class="min-w-0">
            <span class="block text-[12.5px] text-foreground">{{ o.label }}</span>
            <span class="block text-[11px] text-muted-foreground">{{ o.hint }}</span>
          </span>
        </button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      :label="upstream?.title ?? 'Book Covers'"
      :groups="upstream?.groups"
      :items="unsupportedItems"
      note="以下条目在上游该页存在，本项目未实现。「封面搜索提供者」依赖在线封面抓取，与本项目定位冲突；「漫画书脊」依赖漫画支持（第 3 期）。"
    />
  </div>
</template>
