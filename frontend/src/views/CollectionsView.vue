<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { localDate } from '@/lib/format'
import { useDndSort } from '@/composables/useDndSort'
import { useCollectionsStore } from '@/stores/collections'
import { useUiStore } from '@/stores/ui'

/** 收藏夹总览：自建收藏夹的增删改、手动排序与进入。 */
const router = useRouter()
const collections = useCollectionsStore()
const ui = useUiStore()

/** 拖拽 / 键盘（上移下移）共用同一个提交口（第 154 期）。 */
async function move(from: number, to: number): Promise<void> {
  if (to < 0 || to >= collections.items.length || from === to) return
  const ids = collections.items.map((c) => c.id)
  const [moved] = ids.splice(from, 1)
  ids.splice(to, 0, moved)
  try {
    await collections.reorder(ids)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '排序失败')
  }
}

const dnd = useDndSort({ onCommit: (from, to) => void move(from, to) })

const draft = ref('')
const error = ref('')
const creating = ref(false)

/** 行内重命名：正在编辑的收藏夹 id 与输入框内容 */
const editingId = ref<number | null>(null)
const editName = ref('')
const renameError = ref('')

onMounted(() => collections.load(true))

function fmtDate(sec: number): string {
  if (!sec) return '—'
  return localDate(new Date(sec * 1000))
}

async function create(): Promise<void> {
  const name = draft.value.trim()
  if (!name) return
  error.value = ''
  creating.value = true
  try {
    await collections.create(name)
    draft.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    creating.value = false
  }
}

async function remove(id: number, name: string): Promise<void> {
  if (!window.confirm(`删除收藏夹「${name}」？（仅删除收藏，不影响书籍文件）`)) return
  try {
    await collections.remove(id)
  } catch (e) {
    // 第 142 期：删失败原先静默 → 行仍在原地，用户以为界面卡住了
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

function startRename(id: number, name: string): void {
  editingId.value = id
  editName.value = name
  renameError.value = ''
}

function cancelRename(): void {
  editingId.value = null
  editName.value = ''
  renameError.value = ''
}

async function commitRename(id: number): Promise<void> {
  const name = editName.value.trim()
  if (!name) return
  renameError.value = ''
  try {
    await collections.rename(id, name)
    cancelRename()
  } catch (e) {
    renameError.value = e instanceof Error ? e.message : '重命名失败'
  }
}
</script>

<template>
  <div>
    <PageHead title="收藏夹" :desc="`共 ${collections.items.length} 个收藏夹`" />

    <Card class="mb-5">
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="draft"
          type="text"
          placeholder="新建收藏夹名称…"
          class="h-8 min-w-[12rem] flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          @keyup.enter="create"
        >
        <Button variant="primary" :disabled="creating || !draft.trim()" @click="create">
          <Icon name="plus" class="h-3.5 w-3.5" />新建
        </Button>
      </div>
      <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <div v-if="collections.items.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="(c, index) in collections.items"
        :key="c.id"
        :data-collection-card="c.id"
        :draggable="true"
        class="transition-colors hover:border-ring"
        :class="dnd.dragOverIndex.value === index ? 'ring-1 ring-ring' : ''"
        @dragstart="dnd.onDragStart(index, $event)"
        @dragover="dnd.onDragOver(index, $event)"
        @drop.prevent="dnd.onDrop(index)"
        @dragend="dnd.onDragEnd"
      >
        <div class="flex items-center gap-3">
          <!-- 首书封面预览（无成员时回退星标占位） -->
          <div class="h-16 w-12 shrink-0 overflow-hidden rounded-md bg-muted">
            <BookCover
              v-if="c.first_book_id"
              :book="{ id: c.first_book_id, title: c.name, c1: '', c2: '', has_cover: c.first_book_has_cover }"
              :interactive="false"
              :show-title="false"
            />
            <div v-else class="grid h-full w-full place-items-center text-muted-foreground">
              <Icon name="star" class="h-5 w-5" />
            </div>
          </div>

          <div class="min-w-0 flex-1" @click="router.push(`/collections/${c.id}`)">
            <!-- 行内重命名 -->
            <input
              v-if="editingId === c.id"
              v-model="editName"
              type="text"
              class="w-full rounded-md border border-ring bg-card px-2 py-1 text-[13px] font-medium text-foreground outline-none"
              @keyup.enter="commitRename(c.id)"
              @keyup.esc="cancelRename"
              @click.stop
            >
            <div
              v-else
              class="cursor-pointer truncate text-[13px] font-medium text-foreground"
            >{{ c.name }}</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground tabular-nums">
              {{ c.count }} 本 · 最后修改 {{ fmtDate(c.updated_at) }}
            </div>
            <p v-if="editingId === c.id && renameError" class="mt-1 text-[11px] text-destructive">
              {{ renameError }}
            </p>
          </div>

          <div class="flex shrink-0 items-center gap-1">
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              title="上移"
              aria-label="上移"
              :disabled="index === 0"
              @click.stop="move(index, index - 1)"
            >
              <Icon name="chev" class="h-3.5 w-3.5 rotate-180" />
            </button>
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              title="下移"
              aria-label="下移"
              :disabled="index === collections.items.length - 1"
              @click.stop="move(index, index + 1)"
            >
              <Icon name="chev" class="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title="重命名"
              @click.stop="startRename(c.id, c.name)"
            >
              <Icon name="edit" class="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
              title="删除收藏夹"
              @click.stop="remove(c.id, c.name)"
            >
              <Icon name="trash" class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </Card>
    </div>

    <!-- 加载失败：可重试的错误态（不与「还没有收藏夹」空态混淆） -->
    <Card v-else-if="collections.error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>收藏夹加载失败：{{ collections.error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="collections.load(true)">重试</Button>
      </div>
    </Card>

    <EmptyState
      v-else
      icon="star"
      title="还没有收藏夹"
      desc="在上方输入名称新建一个，或在书籍详情页把书加入收藏。"
    />
  </div>
</template>
