<script setup lang="ts">
/**
 * 表格视图的列面板（第 158 期）：列显隐 / 行高密度 / 冻结书名列 + 命名视图（导入导出）。
 *
 * 三条口径：
 *  - 书名与操作列**不可隐藏**（判据在 `stores/tablePrefs.ts`，这里只渲染六列）；
 *  - 命名视图存本机、可导出成 JSON 带走；导入时同名不覆盖（逐条回报 added / skipped）；
 *  - 这个面板**只管表格视图**的外观，不动筛选 / 排序（那两样在书架工具栏）。
 */
import { computed, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Switch from '@/components/ui/Switch.vue'
import { useUiStore } from '@/stores/ui'
import {
  DENSITY_OPTIONS,
  MAX_SAVED_VIEWS,
  TABLE_COLUMNS,
  useTablePrefsStore,
  type TableColumnKey,
} from '@/stores/tablePrefs'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const ui = useUiStore()
const table = useTablePrefsStore()

const viewName = ref('')
const importText = ref('')
const showIO = ref(false)

const exported = computed(() => table.exportViews())

function toggle(key: TableColumnKey): void {
  table.toggleColumn(key)
}

function saveView(): void {
  const v = table.saveView(viewName.value)
  if (!v) {
    ui.toast('先给这份视图起个名字')
    return
  }
  ui.toast(`已保存视图「${v.name}」`)
  viewName.value = ''
}

function applyView(id: string, name: string): void {
  if (table.applyView(id)) ui.toast(`已应用视图「${name}」`)
}

function doImport(): void {
  const r = table.importViews(importText.value)
  if (r.error) {
    ui.toast(`导入失败：${r.error}`)
    return
  }
  ui.toast(`导入完成：新增 ${r.added} 份${r.skipped ? `，跳过 ${r.skipped} 份（同名 / 无效 / 已满）` : ''}`)
  importText.value = ''
}
</script>

<template>
  <div
    v-if="open"
    class="absolute right-0 top-full z-30 mt-1 w-[22rem] rounded-lg border border-border bg-card p-3 shadow-xl"
  >
    <div class="flex items-center gap-2">
      <span class="text-[12.5px] font-medium text-foreground">表格列</span>
      <Button size="sm" variant="ghost" class="ml-auto" @click="emit('close')">关闭</Button>
    </div>
    <p class="mt-1 text-[11px] leading-relaxed text-muted-foreground">
      书名与操作列固定显示；其余列可自行勾选。
    </p>

    <div class="mt-2 grid grid-cols-2 gap-1">
      <label
        v-for="c in TABLE_COLUMNS"
        :key="c.key"
        class="flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-[12px] text-foreground hover:bg-muted"
      >
        <input
          type="checkbox"
          class="h-3.5 w-3.5 cursor-pointer accent-primary"
          :checked="table.prefs.columns.includes(c.key)"
          @change="toggle(c.key)"
        >
        {{ c.label }}
      </label>
    </div>

    <div class="mt-3 border-t border-border pt-2.5">
      <div class="text-[11.5px] text-muted-foreground">行高</div>
      <div class="mt-1 flex gap-1">
        <button
          v-for="d in DENSITY_OPTIONS"
          :key="d.value"
          type="button"
          class="cursor-pointer rounded-md px-2 py-1 text-[11.5px] font-medium transition-colors"
          :class="table.prefs.density === d.value
            ? 'bg-primary text-primary-foreground'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          :title="d.hint"
          @click="table.patch({ density: d.value })"
        >
          {{ d.label }}
        </button>
      </div>
      <label class="mt-2 flex items-center gap-2 text-[12px] text-foreground">
        <Switch
          :model-value="table.prefs.freezeTitle"
          @update:model-value="table.patch({ freezeTitle: $event })"
        />
        冻结书名列
      </label>
    </div>

    <div class="mt-3 border-t border-border pt-2.5">
      <div class="text-[11.5px] text-muted-foreground">命名视图（{{ table.views.length }} / {{ MAX_SAVED_VIEWS }}）</div>
      <ul v-if="table.views.length" class="mt-1 space-y-1">
        <li
          v-for="v in table.views"
          :key="v.id"
          class="flex items-center gap-1 rounded px-1 py-0.5 hover:bg-muted"
        >
          <span class="min-w-0 flex-1 truncate text-[12px] text-foreground">{{ v.name }}</span>
          <Button size="sm" variant="ghost" @click="applyView(v.id, v.name)">应用</Button>
          <Button size="sm" variant="ghost" @click="table.deleteView(v.id)">删除</Button>
        </li>
      </ul>
      <p v-else class="mt-1 text-[11.5px] text-muted-foreground">还没有保存过视图。</p>
      <div class="mt-1.5 flex gap-1">
        <input
          v-model="viewName"
          type="text"
          placeholder="视图名（如「漫画」）"
          aria-label="视图名"
          class="h-7 min-w-0 flex-1 rounded-md border border-border bg-card px-2 text-[11.5px] text-foreground outline-none focus:border-ring"
          @keyup.enter="saveView"
        >
        <Button size="sm" :disabled="!viewName.trim()" @click="saveView">保存当前</Button>
      </div>
    </div>

    <div class="mt-3 border-t border-border pt-2.5">
      <button
        type="button"
        class="cursor-pointer text-[11.5px] text-primary"
        @click="showIO = !showIO"
      >
        {{ showIO ? '收起导入 / 导出' : '导入 / 导出视图' }}
      </button>
      <div v-if="showIO" class="mt-1.5 space-y-1.5">
        <textarea
          :value="exported"
          readonly
          rows="4"
          aria-label="导出的视图 JSON"
          class="w-full rounded-md border border-border bg-muted p-1.5 text-[10.5px] text-muted-foreground"
        />
        <textarea
          v-model="importText"
          rows="4"
          aria-label="导入的视图 JSON"
          placeholder="把导出的 JSON 粘到这里"
          class="w-full rounded-md border border-border bg-card p-1.5 text-[10.5px] text-foreground"
        />
        <Button size="sm" :disabled="!importText.trim()" @click="doImport">导入</Button>
      </div>
    </div>
  </div>
</template>
