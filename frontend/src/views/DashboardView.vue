<script setup lang="ts">
import DashboardScroller from '@/components/dashboard/DashboardScroller.vue'
import DashboardSettingsSheet from '@/components/dashboard/DashboardSettingsSheet.vue'
import DashboardShelfRow from '@/components/dashboard/DashboardShelfRow.vue'
import DashboardWelcome from '@/components/dashboard/DashboardWelcome.vue'
import DashboardWidgetRow from '@/components/dashboard/DashboardWidgetRow.vue'
import { useDashboardStore } from '@/stores/dashboard'

/**
 * 仪表盘：顶部部件行 + 下方书架行，右下角自定义面板。
 *
 * 与 v2 旧仪表盘的关系：**整块替换** —— 原「统计四卡 / 继续阅读封面网格 /
 * 进行中任务 + 书源健康双栏」全部删除，改成 BookOrbit 的两层结构。
 * 那部分能力分别落到了「书库概览」部件、书架行与任务中心。
 */
const dashboard = useDashboardStore()
</script>

<template>
  <DashboardScroller>
    <DashboardWidgetRow />

    <DashboardShelfRow v-for="shelf in dashboard.enabledShelves" :key="shelf.id" :shelf="shelf" />

    <DashboardWelcome v-if="dashboard.isEmpty" />
  </DashboardScroller>

  <DashboardSettingsSheet />
</template>
