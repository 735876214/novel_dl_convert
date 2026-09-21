import { computed } from 'vue'

import { useLibraryStore } from '@/stores/library'

/**
 * 书库 id → 名称（「全部书库」范围下把条目按库分组时要显示归属）。
 *
 * 查不到时回退成 id 本身；id 为空 = **没有库归属**（第 37 期起没有默认库可落）——
 * 宁可显示得朴素也别显示空白，空白会让人误以为这条记录不属于任何库。
 */
export function useLibraryNames() {
  const library = useLibraryStore()

  const names = computed<Record<string, string>>(() => {
    const out: Record<string, string> = {}
    for (const l of library.libraryEntities) out[l.id] = l.name
    return out
  })

  function nameOf(id?: string | null): string {
    const key = String(id || '')
    // 空 id = 这本书挂在某个已移除的库上（或库还没建），如实说「未知书库」
    return names.value[key] || key || '未知书库'
  }

  return { names, nameOf }
}
