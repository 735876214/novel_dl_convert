<script setup lang="ts">
import { computed, ref } from 'vue'

import { useDndSort } from '@/composables/useDndSort'
import { SHELF_TYPE_LABEL, type ShelfType } from '@/data/dashboard'
import { useDashboardStore } from '@/stores/dashboard'
import { useUiStore } from '@/stores/ui'

import { WIDGETS } from './widgets/registry'

/**
 * 右下角「调节」按钮 + 自定义面板。
 *
 * 对应 BookOrbit 的 DashboardSettingsSheet：
 *   · 两个标签页：部件 / 书架
 *   · 逐项开关（未实现的部件置灰并标注「待实现」）
 *   · 拖拽排序（原生 DnD）+ 上下箭头（键盘可达）
 *   · 恢复默认
 *   · 书架可新增，最多 6 行、最少保留 1 行
 */
const dashboard = useDashboardStore()
const ui = useUiStore()

const open = ref(false)
const tab = ref<'widgets' | 'shelves'>('widgets')

const widgetDnd = useDndSort({ onCommit: (from, to) => dashboard.moveWidget(from, to) })
const shelfDnd = useDndSort({ onCommit: (from, to) => dashboard.moveShelf(from, to) })

/** 部件列表按 store 顺序展示（含未实现的，置灰） */
const widgetRows = computed(() =>
  dashboard.widgets.map((pref, index) => ({
    index,
    pref,
    def: WIDGETS.find((w) => w.id === pref.id),
  })),
)

const shelfRows = computed(() =>
  dashboard.shelves.map((shelf, index) => ({ index, shelf })),
)

const ADDABLE_TYPES: ShelfType[] = ['continue', 'recent', 'discover']

function addShelf(type: ShelfType): void {
  if (!dashboard.canAddShelf) {
    ui.toast('最多 6 个书架行')
    return
  }
  dashboard.addShelf({
    id: `shelf-${type}-${Date.now()}`,
    type,
    title: SHELF_TYPE_LABEL[type],
    enabled: true,
  })
}

function removeShelf(id: string): void {
  if (dashboard.shelves.length <= 1) {
    ui.toast('至少保留 1 个书架行')
    return
  }
  dashboard.removeShelf(id)
}

function onReset(): void {
  dashboard.reset()
  ui.toast('已恢复默认布局')
}
</script>

<template>
  <!-- 右下角调节按钮 -->
  <button
    type="button"
    class="fixed right-6 bottom-6 z-40 grid h-11 w-11 cursor-pointer place-items-center rounded-full border border-border bg-card text-foreground shadow-lg transition-transform duration-200 hover:scale-105 hover:text-primary"
    title="自定义仪表盘"
    aria-label="自定义仪表盘"
    @click="open = true"
  >
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" class="h-[18px] w-[18px]">
      <path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h10M18 18h2" />
      <circle cx="16" cy="6" r="2" />
      <circle cx="10" cy="12" r="2" />
      <circle cx="16" cy="18" r="2" />
    </svg>
  </button>

  <!-- 遮罩 -->
  <div
    v-if="open"
    class="fixed inset-0 z-40 bg-black/25 backdrop-blur-[2px]"
    @click="open = false"
  />

  <!-- 右侧滑出面板 -->
  <aside
    class="fixed top-0 right-0 bottom-0 z-50 flex w-[min(23rem,92vw)] flex-col border-l border-border bg-background shadow-2xl transition-transform duration-220 ease-out"
    :class="open ? 'translate-x-0' : 'translate-x-full'"
    role="dialog"
    aria-label="自定义仪表盘"
  >
    <div class="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
      <h3 class="text-[13.5px] font-semibold text-foreground">自定义仪表盘</h3>
      <button
        type="button"
        class="ml-auto grid h-7 w-7 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="关闭"
        @click="open = false"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" class="h-3.5 w-3.5">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>
    </div>

    <!-- 两个标签页 -->
    <div class="flex shrink-0 gap-1 border-b border-border px-3 py-2">
      <button
        v-for="t in (['widgets', 'shelves'] as const)"
        :key="t"
        type="button"
        class="cursor-pointer rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors"
        :class="tab === t ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
        :title="t === 'widgets' ? '部件' : '书架'"
        @click="tab = t"
      >
        {{ t === 'widgets' ? '部件' : '书架' }}
      </button>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-3">
      <!-- ============ 部件 ============ -->
      <template v-if="tab === 'widgets'">
        <div
          v-for="row in widgetRows"
          :key="row.pref.id"
          draggable="true"
          class="mb-1.5 flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2 transition-colors"
          :class="[
            widgetDnd.dragOverIndex.value === row.index ? 'border-primary' : '',
            row.def?.component ? '' : 'opacity-55',
            widgetDnd.dragIndex.value === row.index ? 'opacity-40' : '',
          ]"
          @dragstart="widgetDnd.onDragStart(row.index, $event)"
          @dragover="widgetDnd.onDragOver(row.index, $event)"
          @drop="widgetDnd.onDrop(row.index)"
          @dragend="widgetDnd.onDragEnd()"
        >
          <span class="cursor-grab text-muted-foreground" title="拖拽排序" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="currentColor" class="h-3.5 w-3.5">
              <circle cx="9" cy="6" r="1.4" /><circle cx="15" cy="6" r="1.4" />
              <circle cx="9" cy="12" r="1.4" /><circle cx="15" cy="12" r="1.4" />
              <circle cx="9" cy="18" r="1.4" /><circle cx="15" cy="18" r="1.4" />
            </svg>
          </span>

          <span class="min-w-0 flex-1">
            <span class="block truncate text-[12.5px] font-medium text-foreground">
              {{ row.def?.title ?? row.pref.id }}
              <span v-if="!row.def?.component" class="ml-1 text-[10.5px] font-normal text-muted-foreground">待实现</span>
            </span>
            <span class="mt-0.5 block truncate text-[11px] text-muted-foreground">{{ row.def?.description ?? '' }}</span>
          </span>

          <!-- 键盘可达路径 -->
          <span class="flex shrink-0 flex-col">
            <button
              type="button"
              class="cursor-pointer px-0.5 text-[10px] text-muted-foreground hover:text-primary disabled:cursor-not-allowed disabled:opacity-30"
              :disabled="row.index === 0"
              aria-label="上移"
              @click="dashboard.shiftWidget(row.pref.id, -1)"
            >▲</button>
            <button
              type="button"
              class="cursor-pointer px-0.5 text-[10px] text-muted-foreground hover:text-primary disabled:cursor-not-allowed disabled:opacity-30"
              :disabled="row.index === widgetRows.length - 1"
              aria-label="下移"
              @click="dashboard.shiftWidget(row.pref.id, 1)"
            >▼</button>
          </span>

          <button
            type="button"
            role="switch"
            :aria-checked="row.pref.enabled"
            :disabled="!row.def?.component"
            :title="`显示：${row.def?.title ?? row.pref.id}`"
            class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors disabled:cursor-not-allowed"
            :class="row.pref.enabled ? 'bg-primary' : 'bg-muted'"
            @click="dashboard.toggleWidget(row.pref.id)"
          >
            <span
              class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
              :class="row.pref.enabled ? 'translate-x-[16px]' : 'translate-x-[2px]'"
            />
          </button>
        </div>
      </template>

      <!-- ============ 书架 ============ -->
      <template v-else>
        <div
          v-for="row in shelfRows"
          :key="row.shelf.id"
          draggable="true"
          class="mb-1.5 flex items-center gap-2 rounded-md border border-border bg-card px-2.5 py-2"
          :class="[
            shelfDnd.dragOverIndex.value === row.index ? 'border-primary' : '',
            shelfDnd.dragIndex.value === row.index ? 'opacity-40' : '',
          ]"
          @dragstart="shelfDnd.onDragStart(row.index, $event)"
          @dragover="shelfDnd.onDragOver(row.index, $event)"
          @drop="shelfDnd.onDrop(row.index)"
          @dragend="shelfDnd.onDragEnd()"
        >
          <span class="cursor-grab text-muted-foreground" title="拖拽排序" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="currentColor" class="h-3.5 w-3.5">
              <circle cx="9" cy="6" r="1.4" /><circle cx="15" cy="6" r="1.4" />
              <circle cx="9" cy="12" r="1.4" /><circle cx="15" cy="12" r="1.4" />
              <circle cx="9" cy="18" r="1.4" /><circle cx="15" cy="18" r="1.4" />
            </svg>
          </span>

          <span class="min-w-0 flex-1">
            <span class="block truncate text-[12.5px] font-medium text-foreground">{{ row.shelf.title }}</span>
            <span class="mt-0.5 block truncate text-[11px] text-muted-foreground">{{ SHELF_TYPE_LABEL[row.shelf.type] }}</span>
          </span>

          <button
            type="button"
            class="shrink-0 cursor-pointer text-[11px] text-muted-foreground hover:text-destructive disabled:cursor-not-allowed disabled:opacity-30"
            :disabled="dashboard.shelves.length <= 1"
            title="移除该书架行"
            @click="removeShelf(row.shelf.id)"
          >移除</button>

          <button
            type="button"
            role="switch"
            :aria-checked="row.shelf.enabled"
            :title="`显示：${row.shelf.title}`"
            class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
            :class="row.shelf.enabled ? 'bg-primary' : 'bg-muted'"
            @click="dashboard.toggleShelf(row.shelf.id)"
          >
            <span
              class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
              :class="row.shelf.enabled ? 'translate-x-[16px]' : 'translate-x-[2px]'"
            />
          </button>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
          <span class="text-[11.5px] text-muted-foreground">新增书架行：</span>
          <button
            v-for="t in ADDABLE_TYPES"
            :key="t"
            type="button"
            class="cursor-pointer rounded-md border border-border px-2 py-1 text-[11.5px] text-foreground transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!dashboard.canAddShelf"
            @click="addShelf(t)"
          >
            + {{ SHELF_TYPE_LABEL[t] }}
          </button>
        </div>
      </template>
    </div>

    <div class="shrink-0 border-t border-border p-3">
      <button
        type="button"
        title="恢复默认布局"
        class="w-full cursor-pointer rounded-md border border-border px-3 py-2 text-[12.5px] font-medium text-foreground transition-colors hover:bg-muted"
        @click="onReset"
      >
        恢复默认布局
      </button>
    </div>
  </aside>
</template>
