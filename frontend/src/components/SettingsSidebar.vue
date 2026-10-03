<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import SidebarSectionHeader from '@/components/sidebar/SidebarSectionHeader.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import { useSettingsSearch } from '@/composables/useSettingsSearch'
import { useLibraryStore } from '@/stores/library'
import {
  PAGE_FEATURE,
  SETTINGS_GROUPS,
  findSettingsGroup,
  findSettingsPage,
  type SettingsGroupDef,
} from '@/data/settingsNav'

const route = useRoute()
const router = useRouter()
const library = useLibraryStore()
const search = useSettingsSearch()
const { setOpenMobile } = useSidebar()

/** 窄屏下点完就走：抽屉是模态浮层，不收起来用户会以为「点了没反应」。见 AppSidebar 同名函数 */
function closeMobileDrawer(): void {
  setOpenMobile(false)
}

/**
 * 按**当前库的能力**裁剪设置页（第 10 期「全量显隐」的一部分）：
 * 漫画库里不显示「有声书」阅读设置，有声书库里不显示元数据抓取那几页。
 * 整组都被裁掉的分组也不显示（否则会留下一个点开是空的分组头）。
 */
const groups = computed(() =>
  SETTINGS_GROUPS.map((g) => ({
    ...g,
    pages: g.pages.filter((pg) => {
      const need = PAGE_FEATURE[pg.path]
      return !need || library.hasFeature(need)
    }),
  })).filter((g) => g.pages.length > 0),
)

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

/** 返回主界面（仪表盘） */
function goHome(): void {
  closeMobileDrawer()
  router.push('/')
}
</script>

<template>
  <!-- 第 90 期：与 `AppSidebar` 同一套 `Sidebar*` 体系 —— 折叠 / 抽屉 / 拉手
       全部共用，两个侧栏的行为**逐字一致**（计划里「SettingsSidebar 表现一致」那条）。 -->
  <Sidebar collapsible="icon" variant="floating">
    <!-- 顶部：返回主界面。图标条态下只剩箭头，靠悬停提示认出是「返回主界面」。 -->
    <SidebarHeader class="px-3 pt-3 pb-2">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            as="button"
            type="button"
            tooltip="返回主界面"
            class="text-[13px] font-medium"
            @click="goHome"
          >
            <Icon name="arrowLeft" class="h-[1.0625rem] w-[1.0625rem] shrink-0" />
            <span class="min-w-0 flex-1 truncate group-data-[collapsible=icon]:hidden">返回主界面</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarHeader>

    <!-- 列标题 -->
    <div class="flex shrink-0 items-center gap-2.5 border-b border-border px-3.5 pb-3 group-data-[collapsible=icon]:px-2">
      <div class="grid h-[1.875rem] w-[1.875rem] shrink-0 place-items-center rounded-sm bg-primary font-serif text-[15px] leading-none font-bold text-primary-foreground">
        书
      </div>
      <div class="truncate text-[14.5px] font-semibold tracking-[-0.01em] text-sidebar-foreground group-data-[collapsible=icon]:hidden">设置</div>
    </div>

    <!-- 设置分组导航 -->
    <SidebarContent class="py-3">
      <SidebarGroup v-for="g in groups" :key="g.id" class="py-0.5">
        <!-- 分组头：可折叠。图标 + 中文名 + 英文名（宽屏才显示） -->
        <SidebarSectionHeader :label="g.zh" :is-open="open.has(g.id)" @toggle="toggle(g)">
          <span
            class="flex min-w-0 flex-1 items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em]"
            :class="activeGroupId === g.id ? 'text-foreground' : 'text-muted-foreground'"
          >
            <Icon :name="g.icon" class="h-3.5 w-3.5 shrink-0" />
            <span class="truncate">{{ g.zh }}</span>
            <span class="hidden font-mono text-[10px] font-normal opacity-60 lg:inline">{{ g.label }}</span>
          </span>
        </SidebarSectionHeader>

        <!-- 分组内页面 -->
        <SidebarGroupContent v-show="open.has(g.id)">
          <SidebarMenu>
            <SidebarMenuItem v-for="pg in g.pages" :key="pg.path">
              <SidebarMenuButton
                as-child
                :is-active="currentPage?.path === pg.path"
                :tooltip="pg.zh"
                class="text-[12.5px] text-muted-foreground"
              >
                <RouterLink
                  :to="`/settings/${pg.path}`"
                  :title="`${pg.zh} · ${pg.label}`"
                  @click="closeMobileDrawer"
                >
                  <span class="min-w-0 flex-1 truncate group-data-[collapsible=icon]:hidden">{{ pg.zh }}</span>
                  <!--
                    条目右侧的状态标识（本就在外层套了一层「图标条态隐藏」的壳，
                    所以下面那两个 `lg:inline` 不会跟折叠态的 `hidden` 抢先后）：
                      · 本项目补充（own）—— 上游没有这一页，防止对读时误判
                      · 未支持（placeholder）—— 点进去前就知道该页只做上游对照
                    own 页优先显示「本项目补充」：它更具体，且该页自己会写明是否已实现。
                  -->
                  <span class="shrink-0 group-data-[collapsible=icon]:hidden">
                    <span
                      v-if="pg.own"
                      class="hidden rounded bg-muted px-1 text-[10px] text-muted-foreground lg:inline"
                    >本项目补充</span>
                    <span
                      v-else-if="pg.status === 'placeholder'"
                      class="hidden rounded bg-muted px-1 text-[10px] text-muted-foreground lg:inline"
                    >未支持</span>
                  </span>
                </RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <!-- 底部：设置项搜索入口（对齐上游侧栏底部的 Cmd K 提示） -->
    <SidebarFooter class="border-t border-border p-2">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            as="button"
            type="button"
            tooltip="搜索设置项（Ctrl/⌘ + K）"
            class="text-[12.5px] text-muted-foreground"
            @click="search.openPanel()"
          >
            <Icon name="search" class="h-3.5 w-3.5 shrink-0" />
            <span class="min-w-0 flex-1 truncate text-left group-data-[collapsible=icon]:hidden">搜索设置项</span>
            <span class="shrink-0 group-data-[collapsible=icon]:hidden">
              <kbd class="hidden rounded border border-border bg-muted px-1 py-0.5 font-mono text-[10px] text-muted-foreground lg:inline">⌘K</kbd>
            </span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>

    <SidebarRail />
  </Sidebar>
</template>
