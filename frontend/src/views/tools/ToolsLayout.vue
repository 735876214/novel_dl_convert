<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'

import { useLibraryStore } from '@/stores/library'

/**
 * 工具页外壳。
 *
 * 结构照搬 BookOrbit 的 `client/src/features/tools/views/ToolsView.vue`
 * + `components/ToolsHeader.vue`（AGPL-3.0，归属见仓库 NOTICE）：
 * 顶部一条 h-11 的横向下划线标签栏 + 嵌套 router-view + KeepAlive。
 *
 * 与上游的四处**有意差异**：
 *   1. 去掉它自带的卡片外框与内边距 —— 本项目 `App.vue` 的主区本身已是卡片，
 *      原样照搬会出现双层卡片 + 双份内边距。
 *   2. `KeepAlive :max` 由 3 提到 8（标签从 4 个变 8 个），否则轮换时缓存被
 *      LRU 淘汰，列表 / 筛选 / 滚动位置会反复重建。
 *   3. 上游用 hasPermission 过滤标签，本项目用**库类型的能力清单**过滤
 *      （第 10 期）：漫画库里不显示「本地转换」，有声书库里不显示「书源管理」。
 *   4. 多了「书库管理」一页（上游在设置页里，本项目提到工具页更好找）。
 */

interface ToolSection {
  label: string
  routeName: string
  /** 所需能力（不声明 = 通用工具）；真值源在后端 core/features.py */
  feature?: string
}

/** 声明顺序：书库管理 → BookOrbit 的 4 个工具 → 本项目原有的功能页 */
const SECTIONS: ToolSection[] = [
  { label: '书库管理', routeName: 'tools-libraries' },
  { label: '实体管理', routeName: 'tools-entity-manager' },
  { label: '批量重命名', routeName: 'tools-bulk-rename' },
  { label: '重复书籍', routeName: 'tools-duplicate-books' },
  { label: '缺失资源', routeName: 'tools-missing-resources' },
  { label: '书源管理', routeName: 'tools-sources', feature: 'sources' },
  { label: '导出目录', routeName: 'tools-output' },
  { label: '本地转换', routeName: 'tools-local', feature: 'convert' },
  { label: '转换日志', routeName: 'tools-logs' },
]

const route = useRoute()
const router = useRouter()
const library = useLibraryStore()

/** 可见标签：按**当前库**的能力裁剪（未选库 = 全部可见） */
const visibleSections = computed(() =>
  SECTIONS.filter((s) => !s.feature || library.hasFeature(s.feature)),
)

function go(section: ToolSection): void {
  if (route.name === section.routeName) return
  router.push({ name: section.routeName })
}
</script>

<template>
  <!-- 负外边距抵消 main 的内边距，使标签栏贴齐卡片内缘；内容区再自行补回内边距 -->
  <div class="-m-[var(--shell-content-gutter)] flex flex-col">
    <div
      class="no-scrollbar sticky top-0 z-10 flex h-11 shrink-0 snap-x snap-mandatory items-stretch overflow-x-auto border-b border-border bg-[var(--shell-surface)] px-4 backdrop-blur-md md:snap-none"
      role="tablist"
      aria-label="工具"
    >
      <button
        v-for="section in visibleSections"
        :key="section.routeName"
        type="button"
        role="tab"
        :aria-selected="route.name === section.routeName"
        class="h-full shrink-0 cursor-pointer snap-start border-b-2 px-3 text-sm font-medium whitespace-nowrap transition-colors"
        :class="
          route.name === section.routeName
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
        "
        @click="go(section)"
      >
        {{ section.label }}
      </button>
    </div>

    <!-- 内容区上内边距取两倍 gutter：标签栏与内容之间留出更明显的呼吸感。
         用显式 px/pt/pb 而非 p-[…] + pt-[…]，避免依赖同一属性的工具类排序。 -->
    <div class="px-[var(--shell-content-gutter)] pt-[calc(var(--shell-content-gutter)*2)] pb-[var(--shell-content-gutter)]">
      <RouterView v-slot="{ Component, route: childRoute }">
        <KeepAlive :max="8">
          <component :is="Component" :key="childRoute.name ?? childRoute.path" />
        </KeepAlive>
      </RouterView>
    </div>
  </div>
</template>
