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
 *      （第 10 期）：漫画库里不显示「本地导入」，有声书库里不显示「书源管理」。
 *   4. 本项目原有「书库管理」一页，**第 49 期已迁回设置页**（settings-libraries），
 *      工具页不再单列 —— 与上游一致：书库管理本就属于设置页。
 */

interface ToolSection {
  label: string
  routeName: string
  /** 所需能力（不声明 = 通用工具）；真值源在后端 core/features.py */
  feature?: string
}

/** 声明顺序：BookOrbit 的 4 个工具 → 本项目原有的功能页（书库管理第 49 期已迁到设置页） */
const SECTIONS: ToolSection[] = [
  { label: '实体管理', routeName: 'tools-entity-manager' },
  { label: '重复书籍', routeName: 'tools-duplicate-books' },
  { label: '缺失资源', routeName: 'tools-missing-resources' },
  { label: '书源管理', routeName: 'tools-sources', feature: 'sources' },
  // 第 86 期能力的接线页（导入 / 台账 / 登录 / 验证）：与「书源管理」同一能力键
  { label: '书源工具', routeName: 'tools-source-tools', feature: 'sources' },
  { label: '导出目录', routeName: 'tools-output' },
  // 标签跟 `features.labels()["convert"]` 同步：第 62 期 TXT 改成「只入库不转换」后，
  // 这个页面（路由名仍是 tools-local）做的是**手动投递入库**，不再是转换。
  { label: '本地导入', routeName: 'tools-local', feature: 'convert' },
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

/** 窄屏下拉的换页（`<select>` 只有一个 change 事件，路由名从 DOM 上读） */
function goByName(e: Event): void {
  const name = (e.target as HTMLSelectElement).value
  if (!name || route.name === name) return
  router.push({ name })
}
</script>

<template>
  <!-- 负外边距抵消 main 的内边距，使标签栏贴齐卡片内缘；内容区再自行补回内边距 -->
  <div class="-m-[var(--shell-content-gutter)] flex min-w-0 flex-col">
    <!-- 窄屏（<640px，与 `lib/viewport.ts` 的 NARROW_QUERY 同一档）：8 个标签换成原生下拉。
         360 档标签条按 4 字 × 8 个换行要**三行**（实测 132px 条高），既压内容又难看；
         换成一个 44px 的下拉条，形态与 `BrowseView.vue` 的「窄屏维度栏折叠成下拉」一致。
         ⚠️ 下拉**不是隐藏**：8 个页一个都没少，只是换了控件 —— 第 91 期的教训是
         「唯一入口不许被藏掉」，这里每个入口都仍可点。 -->
    <div
      class="sticky top-0 z-10 flex h-11 shrink-0 items-center border-b border-border bg-[var(--shell-surface)] px-4 backdrop-blur-md sm:hidden"
    >
      <select
        :value="route.name"
        aria-label="工具"
        class="h-8 w-full min-w-0 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
        @change="goByName($event)"
      >
        <option v-for="section in visibleSections" :key="section.routeName" :value="section.routeName">
          {{ section.label }}
        </option>
      </select>
    </div>

    <!-- ⚠️ 标签条**必须换行，不许横向滚动**（第 92 期）：8 个标签在实测里约 672px，
         而 768 档（侧栏展开 240）内容盒只有 ~492px ⇒ 原先的 `overflow-x-auto` 会把尾部标签
         滚出视口。「滚出视口」对横向可达性检查（`.codebuddy/tools/ui-smoke.ps1` 的 `off`）而言
         与「被裁掉」等价 —— 用户看不到、也不会想到那里还能滑。
         改成 `flex-wrap` 后：装不下就换行、装得下就完全惰性（≥1024 逐字与改前一致）。
         高度由 `h-11` 改成 `min-h-11`：单行时仍是 44px（按钮 `py-3` + `text-sm` 行高 20 = 44），
         换行时按行数自然增高。
         ⚠️ 之所以不只靠下拉、还要给宽屏留 `flex-wrap`：侧栏宽度用户可拖（224–480），
         固定断点算不准「还剩多少位置」；`flex-wrap` 没有魔数，任何宽度都不会溢出。 -->
    <div
      class="sticky top-0 z-10 hidden min-h-11 shrink-0 flex-wrap items-stretch border-b border-border bg-[var(--shell-surface)] px-4 backdrop-blur-md sm:flex"
      role="tablist"
      aria-label="工具"
    >
      <button
        v-for="section in visibleSections"
        :key="section.routeName"
        type="button"
        role="tab"
        :aria-selected="route.name === section.routeName"
        class="flex shrink-0 cursor-pointer items-center border-b-2 px-3 py-3 text-sm font-medium whitespace-nowrap transition-colors"
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
         用显式 px/pt/pb 而非 p-[…] + pt-[…]，避免依赖同一属性的工具类排序。
         ⚠️ 这里**曾经**是 `overflow-x-auto` + `min-w-[32rem]`（512px）的「最小可读宽度 + 横滚」：
         第 86 期为了绕开「极窄屏下卡片被压成 12px、中文竖排单字」才加的。
         但 360 档内容盒只有 ~328px ⇒ 512px 的内容有 **184px 常驻在视口外**，
         用户必须横向滚动才能看到右侧的表单按钮与卡片右半（实测 `off=9`）。
         第 92 期改为**让内容跟着视口自适应**：去掉宽度下限与横滚，
         逐页把窄屏会撑破的行内元素组收成可换行 / 可堆叠（见各工具视图）。
         这样窄屏不需要任何横向滚动，`off` 才能真的归零。 -->
    <div class="px-[var(--shell-content-gutter)] pt-[calc(var(--shell-content-gutter)*2)] pb-[var(--shell-content-gutter)]">
      <RouterView v-slot="{ Component, route: childRoute }">
        <KeepAlive :max="8">
          <component :is="Component" :key="childRoute.name ?? childRoute.path" />
        </KeepAlive>
      </RouterView>
    </div>
  </div>
</template>
