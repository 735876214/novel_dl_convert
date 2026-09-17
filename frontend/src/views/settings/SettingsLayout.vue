<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import {
  SETTINGS_GROUPS,
  findSettingsGroup,
  findSettingsPage,
  type SettingsGroupDef,
} from '@/data/settingsNav'

/**
 * 设置页外壳：左侧分组导航 + 面包屑 + 子路由出口。
 *
 * 结构对齐上游 BookOrbit：6 个分组（5 个上游 + 1 个「本项目扩展」），
 * 每个叶子页有独立 URL（`/settings/<域>/<页>`），可直接分享与刷新。
 * 取代原先「单页 + 页内标签栏」的 v-show 实现。
 */
const route = useRoute()

/** 相对 `/settings/` 的子路径 */
const rel = computed(() => route.path.replace(/^\/settings\/?/, ''))
const currentPage = computed(() => findSettingsPage(rel.value))
const currentGroup = computed(() => findSettingsGroup(rel.value))
const activeGroupId = computed(() => currentGroup.value?.id ?? '')

/** 展开的分组：默认展开当前所在分组，并保留「本项目扩展」常驻展开 */
const open = ref<Set<string>>(new Set(['you', 'ext']))

watch(
  activeGroupId,
  (id) => {
    if (id && !open.value.has(id)) open.value = new Set([...open.value, id])
  },
  { immediate: true },
)

function toggle(g: SettingsGroupDef): void {
  const next = new Set(open.value)
  if (next.has(g.id)) next.delete(g.id)
  else next.add(g.id)
  open.value = next
}

function groupCount(g: SettingsGroupDef): number {
  return g.pages.filter((p) => p.status === 'ready').length
}
</script>

<template>
  <div>
    <PageHead title="设置" desc="与上游 BookOrbit 设置页分区结构对齐" />

    <div class="flex flex-col gap-6 lg:flex-row">
      <!-- ============ 左侧分组导航 ============ -->
      <nav
        aria-label="Settings sections"
        class="flex shrink-0 gap-1 overflow-x-auto pb-1 lg:w-56 lg:flex-col lg:gap-3 lg:overflow-visible lg:pb-0"
      >
        <div v-for="g in SETTINGS_GROUPS" :key="g.id" class="shrink-0 lg:shrink">
          <!-- 分组头：可折叠 -->
          <button
            type="button"
            class="flex w-full shrink-0 cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition-colors"
            :class="
              activeGroupId === g.id
                ? 'text-foreground'
                : 'text-muted-foreground hover:text-foreground'
            "
            :aria-expanded="open.has(g.id)"
            @click="toggle(g)"
          >
            <Icon :name="g.icon" class="h-3.5 w-3.5 shrink-0" />
            <span class="whitespace-nowrap">{{ g.zh }}</span>
            <span class="hidden font-mono text-[10px] font-normal opacity-60 lg:inline">{{ g.label }}</span>
            <Icon
              name="chev"
              class="ml-auto hidden h-3 w-3 shrink-0 transition-transform lg:block"
              :class="open.has(g.id) ? '' : '-rotate-90'"
            />
          </button>

          <!-- 分组内页面 -->
          <div v-show="open.has(g.id)" class="lg:mt-0.5 lg:space-y-0.5 lg:border-l lg:border-border lg:pl-2">
            <RouterLink
              v-for="pg in g.pages"
              :key="pg.path"
              :to="`/settings/${pg.path}`"
              :title="`${pg.zh} · ${pg.label}`"
              class="flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors lg:w-full lg:whitespace-normal"
              :class="
                currentPage?.path === pg.path
                  ? 'bg-muted font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
              "
            >
              <span class="min-w-0 flex-1">{{ pg.zh }}</span>
              <!-- 未支持页给出明确标识，避免用户点进去才发现 -->
              <span
                v-if="pg.status === 'placeholder'"
                class="hidden shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground lg:inline"
              >未支持</span>
            </RouterLink>
          </div>
        </div>
      </nav>

      <!-- ============ 右侧内容 ============ -->
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
