<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import DropdownMenu from '@/components/ui/DropdownMenu.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, apiErrorMessage, type BookCard } from '@/lib/api'
import { useBookMenu } from '@/lib/bookMenu'
import { isAudioBook, openTargetOf } from '@/lib/bookOpen'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 书卡的 ⋮ 扩展菜单（第 64 期）。
 *
 * 对齐上游 Book Orbit 书卡的九项菜单，本项目落五项：**阅读/收听、快速预览、下载、
 * 书籍详细信息、删除**。上游的「通过电子邮件发送」**不做** —— 界面上不出现、不灰置、
 * 不占位（灰置等于承认「本该有但不给你」，比没有更糟）。剩下的三项子菜单
 * （添加到收藏 / 设置状态 / 编辑元数据）在 3/3 补。
 *
 * ## 谁持有状态
 *
 * 开合状态在 `lib/bookMenu.ts`（模块单例，一屏只可能开一个），本组件只读它；
 * **列表刷新与预览浮层交给父组件**（emit `preview` / `changed`）—— 本组件不知道
 * 自己长在网格、列表还是表格里，也不该去改书架的数组。
 */
const props = withDefaults(
  defineProps<{
    book: BookCard
    /** **行 key**（不是 bookId）：同一本书在一屏出现两次时两个 ⋮ 不能互相串开 */
    menuKey: string
    /** 只影响触发器外观与 ⋮ 的落点，不影响菜单内容 */
    variant?: 'grid' | 'list' | 'table'
  }>(),
  { variant: 'grid' },
)

const emit = defineEmits<{
  (e: 'preview', book: BookCard): void
  (e: 'changed', book: BookCard, kind: 'status' | 'collection' | 'deleted'): void
}>()

const router = useRouter()
const ui = useUiStore()
const library = useLibraryStore()
const menu = useBookMenu()

const open = computed(() => menu.isOpen(props.menuKey))
const title = computed(() => props.book.title || props.book.name)
const target = computed(() => openTargetOf(props.book))

/**
 * 有声书**不给「下载」**：整本是一个目录，`files[]` 为空，没有可下的单个文件
 *（单文件有声书 `.m4b` 在卡片上与目录型无法区分，见 `BookCard` 没有 `is_dir`）。
 * 属**少给**而不是错给 —— 点下去 404 才是错给。
 */
const canDownload = computed(() => !isAudioBook(props.book) && !!props.book.name)

/**
 * 触发器外观（按视图）。网格是压在封面右下角的小圆片 ——
 * **不做「hover 才出现」**：触屏上那等于没有入口。
 */
const TRIGGER_CLS: Record<string, string> = {
  grid: 'grid h-6 w-6 cursor-pointer place-items-center rounded bg-black/60 text-white backdrop-blur-sm transition-colors hover:bg-black/85',
  list: 'grid h-7 w-7 cursor-pointer place-items-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
  table:
    'grid h-7 w-7 cursor-pointer place-items-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
}

/** 网格卡里 ⋮ 的落点：封面右下角（右上角被格式徽章占着，右下角的「N 册」属系列行、不给菜单） */
const TRIGGER_POS: Record<string, string> = {
  grid: 'absolute right-1.5 bottom-1.5 z-20',
  list: '',
  table: '',
}

const ITEM =
  'flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[12.5px] text-foreground transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40'

function close(): void {
  menu.close()
}

function startReading(): void {
  const t = target.value
  close()
  if (t) void router.push(t.to)
}

function preview(): void {
  close()
  emit('preview', props.book)
}

function openDetail(): void {
  close()
  void router.push(`/book/${props.book.id}`)
}

/**
 * 下载主文件。造 `<a download>` 并点它 —— 与详情页 hero 的下载按钮**逐字同款**
 *（`/download` 不在 `/api` 前缀下、要不了 Bearer 头，故不能走 `request()`）。
 *
 * ⚠️ 文件名取路径**最后一段**：Komga 布局下 `name` 是 `三体/三体 #1.epub`，
 * `download` 属性里带 `/` 会被浏览器当成路径，文件名变成一串怪东西。
 */
function download(): void {
  close()
  const name = props.book.name
  const a = document.createElement('a')
  a.href = api.downloadUrl(name, props.book.library_id)
  a.download = name.split('/').pop() || name
  a.click()
}

const stemOf = (n: string): string => n.replace(/\.[^./]+$/, '')

/**
 * 确认文案里的兄弟文件名单（同目录、同 stem 的其它格式）。
 *
 * **只在用户真的点了「删除」时才拉**，而且走 `library.getBookDetail`（缓存优先）——
 * 多数时候零请求。拉失败就退化成不带这一行的文案：**不影响删除**，
 * 少一句提醒比删不掉好。
 */
async function siblingNames(): Promise<string[]> {
  const d = await library.getBookDetail(props.book.id)
  const files = d?.files ?? []
  const main = props.book.name
  return files
    .map((f) => f.name)
    .filter((n) => n !== main && !!main && stemOf(n) === stemOf(main))
    .map((n) => n.split('/').pop() || n)
}

/**
 * 删除：文件**移入回收站**（不真删），进度 / 批注 / 书签 / 评分一律保留。
 *
 * 确认文案用 `window.confirm`（全站 20 余处惯例，不为这一处新增确认组件）。
 * 第三行**只在真有同 stem 兄弟时才出** —— 没有兄弟却写「其它格式不会被删除」
 * 会让人以为有别的格式存在。
 */
async function remove(): Promise<void> {
  close()
  const sibs = await siblingNames()
  const lines = [
    `确定删除《${title.value}》？`,
    '',
    '· 文件会移入回收站（可恢复，不是真删）',
    '· 阅读进度 / 批注 / 书签 / 评分会保留',
  ]
  if (sibs.length) lines.push(`· 同名的其它格式文件（${sibs.join('、')}）不会被删除`)
  // 用户点「取消」⇒ **一个请求都不发**（双向哨兵：既没删，也没白问一次后端）
  if (!window.confirm(lines.join('\n'))) return

  try {
    await api.deleteBook(props.book.id)
    ui.toast(`《${title.value}》已移入回收站`)
    emit('changed', props.book, 'deleted')
  } catch (e) {
    // 删失败就什么都不动（后端也是「文件没动成就什么都不动」），
    // 所以这里**不 emit** —— 列表没必要为一次无效操作重拉一遍
    ui.toast(apiErrorMessage(e, '删除失败'))
  }
}
</script>

<template>
  <DropdownMenu
    :open="open"
    :trigger-class="TRIGGER_POS[props.variant]"
    @toggle="menu.toggle(props.menuKey)"
    @close="close"
  >
    <template #trigger>
      <button
        type="button"
        data-book-menu-trigger
        :class="TRIGGER_CLS[props.variant]"
        :title="`更多操作：${title}`"
        :aria-label="`更多操作：${title}`"
        aria-haspopup="menu"
        :aria-expanded="open"
      >
        <!-- `more` 图标是横向三点，转 90° 得到上游那样的竖排 ⋮（转比换字体字符可靠） -->
        <Icon name="more" class="h-4 w-4 rotate-90" />
      </button>
    </template>

    <template #panel>
      <button v-if="target" type="button" role="menuitem" :class="ITEM" @click="startReading">
        <Icon :name="target.label === '收听' ? 'volume' : 'book'" class="h-4 w-4 text-muted-foreground" />
        {{ target.label }}
      </button>

      <button type="button" role="menuitem" :class="ITEM" @click="preview">
        <Icon name="layers" class="h-4 w-4 text-muted-foreground" />
        快速预览
      </button>

      <button v-if="canDownload" type="button" role="menuitem" :class="ITEM" @click="download">
        <Icon name="download" class="h-4 w-4 text-muted-foreground" />
        下载
      </button>

      <button type="button" role="menuitem" :class="ITEM" @click="openDetail">
        <Icon name="file" class="h-4 w-4 text-muted-foreground" />
        书籍详细信息
      </button>

      <div class="my-1 border-t border-border" />

      <button
        type="button"
        role="menuitem"
        :class="[ITEM, 'text-destructive hover:bg-destructive/10']"
        @click="remove"
      >
        <Icon name="trash" class="h-4 w-4" />
        删除
      </button>
    </template>
  </DropdownMenu>
</template>
