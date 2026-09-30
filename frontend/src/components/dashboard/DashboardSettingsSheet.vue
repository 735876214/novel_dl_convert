<script setup lang="ts">
import { computed, ref } from 'vue'

import Icon from '@/components/ui/Icon.vue'
import Switch from '@/components/ui/Switch.vue'
import { useDndSort } from '@/composables/useDndSort'
import {
  SCOPE_OPTIONS,
  SHELF_LAYOUT_LABEL,
  SHELF_ROW_OPTIONS,
  SHELF_TYPE_LABEL,
  type ShelfLayout,
  type ShelfType,
} from '@/data/dashboard'
import { useDashboardStore } from '@/stores/dashboard'
import { useUiStore } from '@/stores/ui'

import { WIDGETS } from './widgets/registry'

/**
 * 自定义面板（对应 BookOrbit 的 DashboardSettingsSheet）。
 *
 * 第 82 期：**改为受控组件**（`v-model:open`）—— 入口移到首页问候语行右侧的按钮，
 * 本组件自带的右下悬浮按钮（FAB）已移除；新增「书架布局」（单列/两列）与
 * 逐书架的「行数（1/2/3）」控件。配置即时生效并持久化（无草稿态，与既有约定一致）。
 *
 * 其余保持：两个标签页、逐项开关（未实现置灰）、拖拽排序（面板内仍是原生
 * `useDndSort`，与部件行的 `vue-draggable-plus` 互不影响）、恢复默认。
 */
const open = defineModel<boolean>('open', { default: false })

const dashboard = useDashboardStore()
const ui = useUiStore()

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

const LAYOUTS: ShelfLayout[] = ['wide', 'two-columns']

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

/** 新增一行「智能书架」：按阅读状态筛选（scope = SMART_KEYS 的键） */
function addScopeShelf(key: string, label: string): void {
  if (!dashboard.canAddShelf) {
    ui.toast('最多 6 个书架行')
    return
  }
  dashboard.addShelf({
    id: `shelf-scope-${key}-${Date.now()}`,
    type: 'scope',
    title: label,
    scope: key,
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
  <!-- 遮罩（受控：由问候语行的「自定义」按钮驱动） -->
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
        <Icon name="x" class="h-3.5 w-3.5" />
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
            <Icon name="grip" class="h-3.5 w-3.5" />
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

          <Switch
            :model-value="row.pref.enabled"
            :disabled="!row.def?.component"
            :title="`显示：${row.def?.title ?? row.pref.id}`"
            @update:model-value="dashboard.toggleWidget(row.pref.id)"
          />
        </div>
      </template>

      <!-- ============ 书架 ============ -->
      <template v-else>
        <!-- 书架布局：单列 / 两列（第 82 期新增，对齐 BookOrbit 的 SHELF_LAYOUT） -->
        <div class="mb-3 rounded-md border border-border bg-card p-2.5">
          <div class="mb-2 text-[11.5px] font-medium text-foreground">书架布局</div>
          <div class="grid grid-cols-2 gap-2">
            <button
              v-for="layout in LAYOUTS"
              :key="layout"
              type="button"
              class="flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-left transition-colors"
              :class="
                dashboard.shelfLayout === layout
                  ? 'border-primary bg-primary/5'
                  : 'border-border hover:border-primary/50'
              "
              :aria-pressed="dashboard.shelfLayout === layout"
              @click="dashboard.setShelfLayout(layout)"
            >
              <Icon
                :name="layout === 'two-columns' ? 'columns' : 'rows'"
                class="h-4 w-4 shrink-0"
                :class="dashboard.shelfLayout === layout ? 'text-primary' : 'text-muted-foreground'"
              />
              <span class="text-[12px] font-medium text-foreground">{{ SHELF_LAYOUT_LABEL[layout] }}</span>
            </button>
          </div>
          <p class="mt-2 text-[10.5px] leading-relaxed text-muted-foreground">
            两列布局在宽屏（≥1280px）生效；窄屏自动回落单列。
          </p>
        </div>

        <div
          v-for="row in shelfRows"
          :key="row.shelf.id"
          draggable="true"
          class="mb-1.5 rounded-md border border-border bg-card px-2.5 py-2"
          :class="[
            shelfDnd.dragOverIndex.value === row.index ? 'border-primary' : '',
            shelfDnd.dragIndex.value === row.index ? 'opacity-40' : '',
          ]"
          @dragstart="shelfDnd.onDragStart(row.index, $event)"
          @dragover="shelfDnd.onDragOver(row.index, $event)"
          @drop="shelfDnd.onDrop(row.index)"
          @dragend="shelfDnd.onDragEnd()"
        >
          <div class="flex items-center gap-2">
            <span class="cursor-grab text-muted-foreground" title="拖拽排序" aria-hidden="true">
              <Icon name="grip" class="h-3.5 w-3.5" />
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

            <Switch
              :model-value="row.shelf.enabled"
              :title="`显示：${row.shelf.title}`"
              @update:model-value="dashboard.toggleShelf(row.shelf.id)"
            />
          </div>

          <!-- 行数：1 / 2 / 3（第 82 期新增，对齐 BookOrbit 的 shelf-rows 控件） -->
          <div class="mt-2 flex items-center gap-2 pl-6">
            <span class="shrink-0 text-[10.5px] text-muted-foreground">行数</span>
            <div class="flex overflow-hidden rounded-md border border-border">
              <button
                v-for="n in SHELF_ROW_OPTIONS"
                :key="n"
                type="button"
                class="h-6 w-7 cursor-pointer text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                :class="
                  (row.shelf.rows ?? 1) === n
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                "
                :disabled="!row.shelf.enabled"
                :aria-pressed="(row.shelf.rows ?? 1) === n"
                @click="dashboard.setShelfRows(row.shelf.id, n)"
              >
                {{ n }}
              </button>
            </div>
            <span class="text-[10.5px] text-muted-foreground">行封面（窄屏自动压到 2 行）</span>
          </div>
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

        <div class="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
          <span class="text-[11.5px] text-muted-foreground">智能书架行：</span>
          <button
            v-for="o in SCOPE_OPTIONS"
            :key="o.key"
            type="button"
            class="cursor-pointer rounded-md border border-border px-2 py-1 text-[11.5px] text-foreground transition-colors hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="!dashboard.canAddShelf"
            @click="addScopeShelf(o.key, o.label)"
          >
            + {{ o.label }}
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
