<script setup lang="ts">
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { THUMBNAIL_CLICK_OPTIONS, useShelfPrefsStore, type ThumbnailClick } from '@/stores/shelfPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Display → Behavior（`/settings/appearance/behavior`）
 *
 * 上游这一页只有三项（LIBRARY BEHAVIOR 组），本项目**三项全做实**，故页面末尾
 * 没有「上游还有、本项目未支持」那张对照卡。
 *
 * ⚠️ 这三项存**本机**（`stores/shelfPrefs` 的 `nf-shelf-prefs`），不进偏好同步载荷 ——
 * 与书架的视图/排序偏好同一档：它们是「书架怎么反应」，不是「外观长什么样」。
 * 页尾写明了这一点，免得用户以为换台设备会跟过来。
 */
const prefs = useShelfPrefsStore()
const ui = useUiStore()

function setThumbnailClick(v: ThumbnailClick): void {
  prefs.patch({ thumbnailClick: v })
  ui.toast(v === 'reader' ? '点封面直接进阅读器' : '点封面先进详情页')
}

function setFiltersDefault(v: boolean): void {
  prefs.patch({ filtersOpenByDefault: v })
}

function setCollapseSeries(v: boolean): void {
  prefs.patch({ collapseSeries: v })
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">浏览行为</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Behavior</span>
    </div>

    <Card padding="none">
      <div class="border-b border-border px-4 py-3.5 md:flex md:items-center md:gap-4">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">缩略图点击</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            点书卡封面后先去哪儿。打不开的格式（MOBI、有声书等）仍会进详情页。
          </div>
        </div>
        <div
          class="mt-3 grid w-full gap-1 rounded-lg border border-border bg-muted/50 p-1 sm:w-auto sm:grid-cols-2 md:mt-0"
        >
          <button
            v-for="o in THUMBNAIL_CLICK_OPTIONS"
            :key="o.value"
            type="button"
            class="flex min-w-0 cursor-pointer items-center gap-1.5 rounded-md px-3 py-1.5 text-left text-xs font-medium transition-colors"
            :class="prefs.prefs.thumbnailClick === o.value
              ? 'bg-card text-foreground shadow-xs'
              : 'text-muted-foreground hover:text-foreground'"
            @click="setThumbnailClick(o.value)"
          >
            <Icon :name="o.value === 'reader' ? 'play' : 'book'" class="h-3.5 w-3.5 shrink-0" />
            <span class="min-w-0">
              <span class="block truncate">{{ o.label }}</span>
              <span class="block truncate text-[10px] font-normal opacity-75">{{ o.hint }}</span>
            </span>
          </button>
        </div>
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">筛选预览默认展开</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            进书架页时，统一筛选面板默认是展开的（展开/收起一次只改当前状态，不改这里）
          </div>
        </div>
        <input
          type="checkbox"
          class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
          :checked="prefs.prefs.filtersOpenByDefault"
          aria-label="筛选预览默认展开"
          @change="setFiltersDefault(($event.target as HTMLInputElement).checked)"
        />
      </div>

      <div class="flex items-center gap-4 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">系列默认折叠</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            同一系列的书在书架里默认合成一张卡 / 一行
          </div>
        </div>
        <input
          type="checkbox"
          class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
          :checked="prefs.prefs.collapseSeries"
          aria-label="系列默认折叠"
          @change="setCollapseSeries(($event.target as HTMLInputElement).checked)"
        />
      </div>
    </Card>

    <p class="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
      这三项存在本机，与书架的视图 / 排序偏好同一份，不随账号同步 ——「偏好与同步」管的是
      阅读与外观偏好（主题、字号、版式等）。
    </p>
  </div>
</template>
