<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import PageHead from '@/components/ui/PageHead.vue'
import { findSettingsGroup, findSettingsPage } from '@/data/settingsNav'

/**
 * 设置页外壳：左侧分组导航已提升到外壳层（SettingsSidebar），
 * 这里只负责内容区：页头 + 面包屑 + 子路由出口。
 *
 * 叶子页有独立 URL（`/settings/<域>/<页>`），可直接分享与刷新。
 */
const route = useRoute()

/** 相对 `/settings/` 的子路径 */
const rel = computed(() => route.path.replace(/^\/settings\/?/, ''))
const currentPage = computed(() => findSettingsPage(rel.value))
const currentGroup = computed(() => findSettingsGroup(rel.value))
</script>

<template>
  <div>
    <PageHead title="设置" desc="与上游 BookOrbit 设置页分区结构对齐" />

    <div class="flex flex-col gap-6 lg:flex-row">
      <!-- 左侧分组导航已移至外壳层 SettingsSidebar（/settings 路由下替换主侧栏） -->
      <div class="min-w-0 flex-1">
        <!-- 面包屑 -->
        <div class="mb-3 flex flex-wrap items-baseline gap-1.5 text-[11.5px] text-muted-foreground">
          <RouterLink to="/settings" class="hover:text-foreground">Settings</RouterLink>
          <template v-if="currentGroup">
            <span class="opacity-50">/</span>
            <span>{{ currentGroup.label }}</span>
          </template>
          <template v-if="currentPage">
            <span class="opacity-50">/</span>
            <span class="text-foreground">{{ currentPage.label }}</span>
          </template>
        </div>

        <RouterView />
      </div>
    </div>
  </div>
</template>
