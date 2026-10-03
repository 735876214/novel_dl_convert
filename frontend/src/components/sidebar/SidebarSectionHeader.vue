<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'

/**
 * 分组标题行（第 90 期，结构照搬 BookOrbit 的 `sidebar/SidebarSectionHeader.vue`）。
 *
 * 一行三件事，**都是真按钮**：折叠标题、可能有的「新增」「更多」。
 * 用真实的 `<button>` 而不是可点 `<div>`：整行可点是必须的（原来的大点击区不能丢），
 * 但键盘也得点得到 —— 这是本期「细节与可达性」那一节要的东西。
 *
 * ⚠️ 折叠开合**只切 `v-show`，不重建 DOM**（AppSidebar 的既有约定）：分组里有筛选
 * 输入框，`v-if` 一重建焦点就没了，「筛到一半折叠一下再展开，光标跑掉」。
 * 所以这里只发 `toggle` 事件，显隐由调用方用 `v-show` 决定。
 *
 * ⚠️ 折叠成图标条时**整行消失**（`group-data-[collapsible=icon]:hidden`）：3rem
 * 宽度放不下「标题 + 两个按钮」，硬挤出来只会是一排糊掉的方块。图标条下靠
 * `SidebarMenuButton` 的悬停提示认路。
 */
const props = withDefaults(
  defineProps<{
    label: string
    isOpen: boolean
    /** 可折叠的组才画箭头、才响应整行点击；不可折叠的组只当标题用 */
    collapsible?: boolean
    actions?: Array<'add' | 'more'>
  }>(),
  { collapsible: true, actions: () => [] },
)

const emit = defineEmits<{
  toggle: []
  action: [action: 'add' | 'more']
}>()

const ACTION_LABEL: Record<'add' | 'more', string> = { add: '新增', more: '更多' }
const ACTION_ICON: Record<'add' | 'more', string> = { add: 'plus', more: 'more' }
</script>

<template>
  <div class="flex h-8 items-center gap-0.5 group-data-[collapsible=icon]:hidden">
    <button
      v-if="props.collapsible"
      type="button"
      class="flex h-8 min-w-0 flex-1 cursor-pointer items-center gap-1.5 rounded-md px-2 text-left outline-hidden transition-colors duration-150 hover:bg-(--shell-accent-wash) focus-visible:ring-2 focus-visible:ring-sidebar-ring"
      :aria-expanded="props.isOpen"
      @click="emit('toggle')"
    >
      <!-- 默认插槽替换的是**整块标题内容**（不是标题里的文字）：
           两个侧栏的组标题长得不一样（主侧栏只有中文名，设置侧栏还有图标与英文名），
           把版式交给调用方，这里只保证「可点、可聚焦、有折叠箭头」。 -->
      <slot>
        <span class="min-w-0 truncate text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">
          {{ props.label }}
        </span>
      </slot>
      <Icon
        name="chev"
        class="ml-auto h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200 motion-reduce:transition-none"
        :class="props.isOpen ? '' : '-rotate-90'"
      />
    </button>
    <p v-else class="min-w-0 flex-1 truncate px-2 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">
      <slot>{{ props.label }}</slot>
    </p>

    <button
      v-for="action in props.actions"
      :key="action"
      type="button"
      class="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground outline-hidden transition-colors duration-150 hover:bg-(--shell-accent-wash) hover:text-primary focus-visible:ring-2 focus-visible:ring-sidebar-ring"
      :title="`${ACTION_LABEL[action]}${props.label}`"
      :aria-label="`${ACTION_LABEL[action]}${props.label}`"
      @click="emit('action', action)"
    >
      <Icon :name="ACTION_ICON[action]" class="h-3 w-3" />
    </button>
  </div>
</template>
