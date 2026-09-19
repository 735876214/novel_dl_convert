<script setup lang="ts">
import { computed } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import PageHead from '@/components/ui/PageHead.vue'
import SettingsSearchPanel from '@/components/settings/SettingsSearchPanel.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { useSettingsDirty } from '@/composables/useSettingsDirty'
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

/**
 * 未保存改动有两个来源（对齐上游各设置页顶部的「未保存」提示）：
 *   · 服务端配置草稿（`useSettingsConfig` 单例，跨页共享，改动不落库）；
 *   · 页面自持草稿（通过 `useSettingsDirty` 上报，如「资料」页的显示名 / 时区）。
 * 各页自己的保存按钮行为不变，这里只提供统一提示与「放弃更改」。
 */
const cfgDraft = useSettingsConfig()
const localDrafts = useSettingsDirty()

const hasDirty = computed(() => cfgDraft.hasDirty.value || localDrafts.hasDirty.value)
/** 能点名的来源（配置草稿涉及哪一页由所在页决定，因此只列出页面自持草稿） */
const dirtySources = computed(() => localDrafts.dirtyLabels.value)

function discardAll(): void {
  cfgDraft.discardDirty()
  localDrafts.discardAll()
}
</script>

<template>
  <div>
    <PageHead title="设置" desc="与上游 BookOrbit 设置页分区结构对齐" />

    <!-- 设置项搜索浮层：⌘K 或侧栏底部按钮唤起 -->
    <SettingsSearchPanel />

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
            <!-- 上游没有这一页：明确标注，避免与上游逐页对读时误判 -->
            <span
              v-if="currentPage.own"
              class="ml-0.5 shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground"
            >本项目补充</span>
            <span
              v-else-if="currentPage.status === 'placeholder'"
              class="ml-0.5 shrink-0 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground"
            >未支持</span>
          </template>
        </div>

        <!-- 未保存变更提示：出现在面包屑下、子页之上，不遮挡页头 -->
        <Transition
          enter-active-class="transition duration-150 ease-out"
          enter-from-class="h-0 -translate-y-1 opacity-0"
          leave-active-class="transition duration-100 ease-in"
          leave-to-class="h-0 -translate-y-1 opacity-0"
        >
          <div
            v-if="hasDirty"
            class="mb-3 flex items-center gap-2 rounded-[10px] border border-warning/30 bg-warning/10 px-3.5 py-2 text-[12px]"
            role="status"
          >
            <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" aria-hidden="true" />
            <span class="font-medium text-foreground">有未保存的改动</span>
            <span v-if="dirtySources.length" class="text-muted-foreground">
              （{{ dirtySources.join('、') }}）
            </span>
            <button
              type="button"
              class="ml-auto shrink-0 cursor-pointer text-[12px] font-medium text-primary hover:underline"
              title="把草稿还原为已保存的值（不会写入服务端）"
              @click="discardAll"
            >放弃更改</button>
          </div>
        </Transition>

        <RouterView />
      </div>
    </div>
  </div>
</template>
