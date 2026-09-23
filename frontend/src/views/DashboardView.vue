<script setup lang="ts">
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import DashboardScroller from '@/components/dashboard/DashboardScroller.vue'
import DashboardSettingsSheet from '@/components/dashboard/DashboardSettingsSheet.vue'
import DashboardShelfRow from '@/components/dashboard/DashboardShelfRow.vue'
import DashboardWelcome from '@/components/dashboard/DashboardWelcome.vue'
import DashboardWidgetRow from '@/components/dashboard/DashboardWidgetRow.vue'
import FirstRunNotice from '@/components/dashboard/FirstRunNotice.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { useStatsStore } from '@/stores/stats'

/**
 * 仪表盘：顶部部件行 + 下方书架行，右下角自定义面板。
 *
 * 与 v2 旧仪表盘的关系：**整块替换** —— 原「统计四卡 / 继续阅读封面网格 /
 * 进行中任务 + 书源健康双栏」全部删除，改成 BookOrbit 的两层结构。
 * 那部分能力分别落到了「书库概览」部件、书架行与任务中心。
 */
const dashboard = useDashboardStore()
const stats = useStatsStore()
</script>

<template>
  <DashboardScroller>
    <!-- 0 库时的首屏引导：压在部件之上，第一个看见的就是「先建书库」（第 38 期） -->
    <FirstRunNotice />

    <!-- 统计拉取失败：部件会各自退化成 0 / 空，这里统一给一条可重试提示（第 49 期） -->
    <Card v-if="stats.error" padding="sm" class="mb-3">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>统计加载失败，部分部件显示不完整：{{ stats.error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="stats.load(true)">重试</Button>
      </div>
    </Card>

    <DashboardWidgetRow />

    <DashboardShelfRow v-for="shelf in dashboard.enabledShelves" :key="shelf.id" :shelf="shelf" />

    <DashboardWelcome v-if="dashboard.isEmpty" />
  </DashboardScroller>

  <DashboardSettingsSheet />
</template>
