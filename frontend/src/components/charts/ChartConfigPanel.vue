<script setup lang="ts">
import { computed } from 'vue'

import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { STATISTICS_CHART_META, type StatisticsChartMeta, type StatisticsTab } from '@/lib/statistics-charts'
import { useStatsChartPrefsStore } from '@/stores/statsChartPrefs'

/**
 * 图表配置面板（对应上游统计页的 Configure 抽屉）。
 *
 * 三处与本项目对齐的改动：
 *
 * 1. **页内面板，不用抽屉**。上游是 shadcn `Sheet` 从右侧滑出（`StatisticsPage.vue:220-267`）；
 *    本项目没有 Sheet 组件，为一个面板新造一套抽屉（遮罩、焦点陷阱、Esc 关闭、滚动锁）
 *    不划算，改成页内可折叠面板 —— 与书架页的统一筛选面板同一种做法。
 * 2. **上移 / 下移按钮，不做拖拽**。上游用 `vue-draggable-plus` + `GripVertical` 把手；
 *    本项目不引拖拽库（见 `ChartGrid.vue` 头注），画一个拖不动的把手就是假交互。
 * 3. **只列当前分区的图**。与上游一致（`StatisticsPage.vue:83` 的 `activeOrderedCharts`）——
 *    顺序本来就是分区内的事。
 */
const props = defineProps<{
  /** 当前分区 */
  tab: StatisticsTab
}>()

const prefs = useStatsChartPrefsStore()

/**
 * 本分区的全部图（**含被隐藏的**），按用户排定的顺序。
 *
 * `order` 里的 id 已经是收窄过的 `StatisticsChartId`，查表必定命中 —— 所以这里
 * **不需要**再 filter 一遍「查不到就丢掉」（那层过滤在 `stores/statsChartPrefs` 的
 * `read()` 里，存档入口做一次就够）。
 */
const rows = computed<StatisticsChartMeta[]>(() =>
  prefs.prefs.order[props.tab].map((id) => STATISTICS_CHART_META[id]),
)

const visibleCount = computed(() => rows.value.filter((m) => prefs.isVisible(m.id)).length)
</script>

<template>
  <Card class="mb-4" padding="sm">
    <div class="mb-2 flex flex-wrap items-center gap-2">
      <Icon name="chart" class="h-3.5 w-3.5 text-muted-foreground" />
      <span class="text-[12.5px] font-medium text-foreground">图表配置</span>
      <span class="text-[11px] text-muted-foreground tabular-nums">
        显示 {{ visibleCount }} / {{ rows.length }}
      </span>
      <button
        type="button"
        class="ml-auto cursor-pointer rounded-md px-2 py-1 text-[11.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        @click="prefs.reset()"
      >
        恢复默认
      </button>
    </div>

    <ul class="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
      <li
        v-for="(m, i) in rows"
        :key="m.id"
        class="flex items-center gap-2 rounded-md border border-border/60 bg-muted/30 px-2.5 py-1.5"
      >
        <Icon
          :name="m.icon"
          class="h-3.5 w-3.5 shrink-0"
          :class="prefs.isVisible(m.id) ? 'text-primary' : 'text-muted-foreground'"
        />
        <span
          class="min-w-0 flex-1 truncate text-[12.5px]"
          :class="prefs.isVisible(m.id) ? 'text-foreground' : 'text-muted-foreground'"
        >
          {{ m.label }}
        </span>
        <span class="shrink-0 text-[10.5px] text-muted-foreground tabular-nums">{{ m.size }}</span>

        <button
          type="button"
          title="上移"
          aria-label="上移"
          :disabled="i === 0"
          class="shrink-0 cursor-pointer rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-default disabled:opacity-30"
          @click="prefs.move(tab, m.id, -1)"
        >
          <Icon name="chev" class="h-3.5 w-3.5 rotate-180" />
        </button>
        <button
          type="button"
          title="下移"
          aria-label="下移"
          :disabled="i === rows.length - 1"
          class="shrink-0 cursor-pointer rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground disabled:cursor-default disabled:opacity-30"
          @click="prefs.move(tab, m.id, 1)"
        >
          <Icon name="chev" class="h-3.5 w-3.5" />
        </button>

        <input
          type="checkbox"
          class="h-4 w-4 shrink-0 cursor-pointer accent-primary"
          :checked="prefs.isVisible(m.id)"
          :aria-label="`显示 ${m.label}`"
          @change="prefs.toggle(m.id)"
        />
      </li>
    </ul>

    <p class="mt-2 text-[11px] text-muted-foreground">
      隐藏只是不画这张图，排在第几位会记着；顺序与显隐只影响本分区，存在本机。
    </p>
  </Card>
</template>
