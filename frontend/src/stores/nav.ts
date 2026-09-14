import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { isShelfGroup, NAV_GROUPS, type NavItem } from '@/data/nav'
import { useUiStore } from './ui'

/**
 * 侧栏 store：分组折叠状态 + 「库」组筛选 + 任务计数。
 *
 * 沿用 v2 的两条实现原则：
 *   · 折叠只切 class，不重建 DOM（因此筛选框输入焦点不会丢）
 *   · 筛选只切条目显隐，不重建列表
 * 在 Vue 里这两条天然成立（用 v-show 而非 v-if 重建）。
 */
const COLLAPSE_KEY = 'nav-collapsed'

function readCollapsed(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(COLLAPSE_KEY)
    if (!raw) return {}
    return (JSON.parse(raw) as Record<string, boolean>) ?? {}
  } catch {
    return {}
  }
}

export const useNavStore = defineStore('nav', () => {
  const groups = NAV_GROUPS
  const collapsed = ref<Record<string, boolean>>(readCollapsed())
  const libFilter = ref('')

  const isCollapsed = computed(() => (title: string) => Boolean(collapsed.value[title]))

  function toggleGroup(title: string): void {
    collapsed.value[title] = !collapsed.value[title]
    try {
      localStorage.setItem(COLLAPSE_KEY, JSON.stringify(collapsed.value))
    } catch {
      /* 存储不可用时忽略 */
    }
  }

  /** 「库」组筛选：只影响条目显隐，输入焦点保持 */
  function setLibFilter(word: string): void {
    libFilter.value = word
  }

  /** 某条导航项在当前筛选下是否可见 */
  function itemVisible(groupTitle: string, item: NavItem): boolean {
    if (groupTitle !== '库' || !libFilter.value) return true
    return item.label.toLowerCase().includes(libFilter.value.toLowerCase())
  }

  function filteredItems(groupTitle: string, items: NavItem[]): NavItem[] {
    if (groupTitle !== '库' || !libFilter.value) return items
    return items.filter((it) => itemVisible(groupTitle, it))
  }

  /** 分组头部的「新增 / 更多」按钮（演示态） */
  function navAction(title: string, action: 'add' | 'more'): void {
    const ui = useUiStore()
    const label = action === 'add' ? '新增' : '更多'
    ui.demo(`${label}${title}`)
  }

  return {
    groups,
    collapsed,
    libFilter,
    isCollapsed,
    toggleGroup,
    setLibFilter,
    itemVisible,
    filteredItems,
    isShelfGroup,
    navAction,
  }
})
