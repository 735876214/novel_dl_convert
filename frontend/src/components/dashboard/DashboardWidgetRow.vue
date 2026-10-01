<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { VueDraggable } from 'vue-draggable-plus'

import Icon from '@/components/ui/Icon.vue'
import { WIDGET_FEATURE } from '@/data/dashboard'
import { useDashboardStore } from '@/stores/dashboard'
import { useLibraryStore } from '@/stores/library'
import { widgetById, type WidgetDef } from './widgets/registry'

/**
 * 部件行：横向卡片带（第 82 期对齐 BookOrbit）。
 *
 * ⚠️ 卡片外壳（大圆角 / 主色描边 / 半透底 / 毛玻璃 / 固定高 / 定宽）**在这一层**，
 * 部件自身只负责「填满卡片 + 统一内边距」—— 双层壳是第 82 期重构消灭的形态差，
 * 因此改宽度 / 圆角 / 描边只动本文件。
 *
 * 行内拖拽用 `vue-draggable-plus`（用户拍板，`frontend/package.json` 已声明理由）：
 * 它基于 pointer/touch 事件，手机上也能直接拖 —— 原生 HTML5 DnD 在触屏不触发
 * `dragstart`（浏览器限制，不是实现问题）。⚠️ 它会直接操作 DOM，所以保留一份
 * `localWidgets` 本地副本，松手提交前不被异步 store 刷新回退（否则会闪一下）。
 *
 * 排序落库走 `dashboard.applyVisibleOrder`（可见子集 → 全量索引的映射，见 store 注释）。
 * 设置面板里的排序仍用既有的原生 `useDndSort`，两处互不影响。
 */
const dashboard = useDashboardStore()
const library = useLibraryStore()

/** 宽度档：`1x1` 窄卡 / `1x1.5` 宽卡（与 BookOrbit 的 widgetSizeClass 一致） */
const WIDGET_SIZE_CLASS: Record<string, string> = {
  '1x1': 'w-[220px]',
  '1x1.5': 'w-[336px]',
}

/** 可见子集：已启用 ∩ 已实现 ∩ 当前库能力满足（未实现在面板里置灰，不占版面） */
const visible = computed(() =>
  dashboard.enabledWidgets
    .map((w) => widgetById(w.id))
    .filter((w): w is NonNullable<typeof w> => Boolean(w?.component))
    // 第 10 期：按当前库能力裁剪（「每日划线」要批注，漫画库里没有）
    .filter((w) => {
      const need = WIDGET_FEATURE[w.id]
      return !need || library.hasFeature(need)
    }),
)

// —— 行内拖拽：本地副本 + 与 store 的可见子集同步 ——
const localWidgets = ref<WidgetDef[]>([...visible.value])
watch(visible, (val) => {
  localWidgets.value = [...val]
})

const scrollEl = ref<HTMLElement | null>(null)

function scrollBy(delta: number): void {
  scrollEl.value?.scrollBy({ left: delta, behavior: 'smooth' })
}

/** 松手后：先落本地副本（不闪），再把可见子集的新顺序写回全量列表 */
function handleReorder(reordered: WidgetDef[]): void {
  localWidgets.value = [...reordered]
  dashboard.applyVisibleOrder(reordered.map((w) => w.id))
}
</script>

<template>
  <section v-if="visible.length > 0" class="group/widgets relative min-w-0">
    <!-- 悬停显现的左右滚动按钮（触屏直接滑，不依赖悬停） -->
    <div
      class="pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover/widgets:opacity-100"
    >
      <div
        class="pointer-events-auto flex items-center gap-0.5 rounded-md border border-border/60 bg-background/65 p-0.5 backdrop-blur-sm"
      >
        <button
          type="button"
          aria-label="向左滚动"
          class="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          @click="scrollBy(-300)"
        >
          <Icon name="chevronLeft" class="h-4 w-4" />
        </button>
        <button
          type="button"
          aria-label="向右滚动"
          class="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          @click="scrollBy(300)"
        >
          <Icon name="chevronRight" class="h-4 w-4" />
        </button>
      </div>
    </div>

    <!-- 横向卡片带：滚动条隐藏但保留滚轮 / 触屏滑动 / 拖拽 -->
    <div
      ref="scrollEl"
      class="no-scrollbar -mx-1 overflow-x-auto px-1 pb-1 pt-1"
    >
      <VueDraggable
        v-model="localWidgets"
        class="flex w-max gap-4"
        handle=".widget-drag-handle"
        :animation="200"
        @update:model-value="handleReorder"
      >
        <div
          v-for="(w, index) in localWidgets"
          :key="w.id"
          class="widget-card-enter group/card relative h-55 shrink-0 overflow-hidden rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]"
          :class="WIDGET_SIZE_CLASS[w.size]"
          :style="{ animation: 'dashboardWidgetFadeUp 0.35s ease both', animationDelay: `${index * 80}ms` }"
        >
          <component :is="w.component" :size="w.size" />

          <!-- 拖拽手柄：悬停卡片显现（拖动排序，不进设置面板也能排） -->
          <div
            class="widget-drag-handle absolute right-2 top-2 z-10 flex h-6 w-6 cursor-grab items-center justify-center rounded-md text-muted-foreground opacity-0 transition-all duration-150 hover:bg-background/80 hover:opacity-100 group-hover/card:opacity-100 active:cursor-grabbing"
            :aria-label="`拖动排序：${w.title}`"
            :title="`拖动排序：${w.title}`"
          >
            <Icon name="grip" class="h-3.5 w-3.5" />
          </div>
        </div>
      </VueDraggable>
    </div>
  </section>
</template>

<style scoped>
/* 逐卡错峰入场（全站只此一份 —— 部件行是卡片带的唯一真值源） */
@keyframes dashboardWidgetFadeUp {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/*
  ⚠️ scoped keyframes 不受 `main.css` 全局 `prefers-reduced-motion` 降级的保护
  （那条只压 duration，且主题是「干脆不播」）——动画由内联样式挂上，所以这里必须
  用 `!important` 才能压过内联声明（第 83 期与封面入场同批补上）。
*/
@media (prefers-reduced-motion: reduce) {
  .widget-card-enter {
    animation: none !important;
  }
}
</style>
