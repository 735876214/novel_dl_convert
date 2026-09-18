<script setup lang="ts">
/**
 * 同名冲突修复（第 13 期）。
 *
 * 冲突 = 两本书的 `book_id` 撞了。`book_id` 由**文件名**派生，所以「A 库有
 * 三体.epub、B 库也有三体.epub」就是同一个 id：进度 / 批注 / 评分只有一份，
 * 详情页会直接打不开（`library.by_id` 抛 `BookIdConflict`）。
 *
 * 修法只能是给其中一本改名 —— 而改名必然换 id，所以应用时**必须搬关联数据**，
 * 否则「修复冲突」等于清空阅读记录。这件事由后端 `fileops.apply_conflict_rename`
 * 负责（同名同库重新投递仍按覆盖放行，入库侧那条闸门只管跨库），这里只做勾选与
 * 回传，不重复实现判据。
 *
 * 与其它工具同一范式：默认建议名由后端给（与迁移 / 入库闸门同一口径 `X (2).ext`），
 * 应用只回传**清单里确认过的条目**，后端会再校验一遍。
 */
import { computed, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { api, type ConflictGroup, type ConflictItem, type ConflictsResult } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const emit = defineEmits<{ (e: 'changed'): void }>()
const ui = useUiStore()

const data = ref<ConflictsResult | null>(null)
const loading = ref(false)
const applying = ref(false)
/** 勾选状态：`库|组id|文件名` → 是否要改名 */
const picked = ref<Record<string, boolean>>({})
/** 建议名的可编辑草稿（默认填后端给的建议名） */
const names = ref<Record<string, string>>({})

function keyOf(group: ConflictGroup, item: ConflictItem): string {
  return `${item.library_id || ''}|${group.id}|${item.name}`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const res = await api.libraryConflicts()
    data.value = res
    picked.value = {}
    names.value = {}
    for (const g of res.groups) {
      for (const it of g.items) {
        if (it.keep) continue
        const k = keyOf(g, it)
        // 默认全选：一组里改一本就够，保留项后端已经标好、不参与勾选
        picked.value[k] = true
        names.value[k] = it.suggest
      }
    }
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取同名冲突失败')
    data.value = null
  } finally {
    loading.value = false
  }
}

void load()
defineExpose({ reload: load })

const groups = computed<ConflictGroup[]>(() => data.value?.groups ?? [])
const pickedCount = computed(() => Object.values(picked.value).filter(Boolean).length)

async function apply(): Promise<void> {
  const items: Array<{ old: string; new: string; library_id: string | null }> = []
  for (const g of groups.value) {
    for (const it of g.items) {
      if (it.keep) continue
      const k = keyOf(g, it)
      if (!picked.value[k]) continue
      const next = (names.value[k] || '').trim()
      if (!next || next === it.name) continue
      items.push({ old: it.name, new: next, library_id: it.library_id })
    }
  }
  if (!items.length) {
    ui.toast('没有可改名的条目（勾选后填写与原名不同的新名）')
    return
  }
  applying.value = true
  try {
    const res = await api.libraryConflictsApply(items)
    ui.toast(
      `已改名 ${res.count} 本，搬迁阅读数据 ${res.remapped} 条${
        res.errors.length ? `；失败 ${res.errors.length} 条` : ''
      }`,
    )
    for (const e of res.errors.slice(0, 3)) ui.toast(`${e.old || ''}：${e.error}`)
    emit('changed')
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '应用失败')
  } finally {
    applying.value = false
  }
}
</script>

<template>
  <div v-if="loading && !data" class="px-4 py-6 text-[12.5px] text-muted-foreground">检查中…</div>
  <div v-else-if="!groups.length" class="px-4 py-6 text-[12.5px] text-muted-foreground">
    没有同名冲突：每本书的文件名都唯一
  </div>
  <template v-else>
    <div class="border-b border-border px-4 py-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">同名冲突</span>
        <Badge>{{ groups.length }} 组</Badge>
        <Badge v-if="data?.cross_library" tone="accent">跨库 {{ data.cross_library }}</Badge>
        <span class="text-[11.5px] text-muted-foreground">已选 {{ pickedCount }} 项</span>
        <Button size="sm" class="ml-auto" :disabled="applying || !pickedCount" @click="apply">
          {{ applying ? '改名中…' : '改名选中项' }}
        </Button>
      </div>
      <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
        两本书文件名相同就会撞上同一个 book_id，阅读进度 / 批注 / 评分只有一份
        —— 详情页会打不开。改其中一本即可；改名会一并把阅读数据搬过去。
      </div>
    </div>

    <div v-for="g in groups" :key="g.id" class="border-b border-border px-4 py-3 last:border-b-0">
      <div class="flex flex-wrap items-center gap-2">
        <Badge :tone="g.cross_library ? 'accent' : undefined">
          {{ g.cross_library ? '跨库' : '库内' }}
        </Badge>
        <span class="text-[12.5px] font-medium text-foreground">{{ g.name }}</span>
        <span class="text-[11.5px] text-muted-foreground">
          {{ g.items.length }} 本 · {{ g.library_count }} 个库
        </span>
        <span class="ml-auto text-[11.5px] text-muted-foreground">{{ g.title }}</span>
      </div>

      <div
        v-for="it in g.items"
        :key="keyOf(g, it)"
        class="mt-2 flex flex-wrap items-center gap-2 text-[11.5px]"
      >
        <template v-if="it.keep">
          <Badge>保留</Badge>
          <code class="min-w-0 flex-1 truncate text-foreground" :title="it.name">{{ it.name }}</code>
          <span class="shrink-0 text-muted-foreground">{{ it.library_name }}</span>
        </template>
        <template v-else>
          <input v-model="picked[keyOf(g, it)]" type="checkbox" />
          <code class="min-w-0 flex-1 truncate text-muted-foreground" :title="it.name">{{ it.name }}</code>
          <span class="shrink-0 text-muted-foreground">→</span>
          <input
            v-model="names[keyOf(g, it)]"
            class="w-60 rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
          />
          <span class="shrink-0 text-muted-foreground">{{ it.library_name }}</span>
        </template>
      </div>
    </div>
  </template>
</template>
