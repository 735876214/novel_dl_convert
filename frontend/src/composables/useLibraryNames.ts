import { computed } from 'vue'

import { useLibraryStore } from '@/stores/library'

/**
 * 书库 id → 名称（「全部书库」范围下把条目按库分组时要显示归属）。
 *
 * 查不到时回退成 id 本身；id 为空时按后端约定落到「默认书库」——
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
    return names.value[key] || key || '默认书库'
  }

  return { names, nameOf }
}
