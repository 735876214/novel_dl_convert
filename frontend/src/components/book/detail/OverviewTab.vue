<script setup lang="ts">
import { computed, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SimilarBooks from '@/components/book/detail/SimilarBooks.vue'
import type { BookCard, BookFile, SimilarBook } from '@/lib/api'
import { api } from '@/lib/api'
import { localDate, localDateToEpoch } from '@/lib/format'
import { useLibraryStore } from '@/stores/library'

/**
 * 概览标签（第 63 期从 `BookDetailView` 抽出）。
 *
 * 排布改动：**右栏只留「版本信息」一块**，成品文件与相似书移到左栏简述卡之下。
 * 改前右栏里塞了进度 / 成品文件 / 相似书三块，而进度已上提到 hero，成品文件的完整
 * 列表本来就在「文件」标签里 —— 挤在窄栏里每行只剩「格式 + 大小」。
 */
const props = defineProps<{
  book: BookCard
  files: BookFile[]
  similar: SimilarBook[]
  similarExpanded: boolean
  /** 与后端 `recommend.MAX_LIMIT` 对齐（接口上限，不是随便取的数） */
  similarMax: number
}>()

const emit = defineEmits<{
  download: [string]
  expandSimilar: []
  openBook: [string]
  /** 入库时间改完后父级重拉详情（book 是 props，不能就地改）。 */
  refresh: []
}>()

/** 与组件 `SimilarBooks` 的 preview 同一个数：父级据此判断「是否可能还有更多」 */
const SIMILAR_PREVIEW = 6

const library = useLibraryStore()
const descOpen = ref(false)

/** 日期格式化（秒 → 本地 YYYY/M/D）；供版本信息「入库」行使用（与文件行 fmtDate 区分） */
function fmtDateSlash(sec?: number): string {
  if (!sec) return '未知'
  const d = new Date(sec * 1000)
  if (Number.isNaN(d.getTime())) return '未知'
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`
}

function fmtSize(n: number): string {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(ts: number): string {
  if (!ts) return '—'
  return localDate(new Date(ts * 1000))
}

/**
 * 书的归属书库名（`library_id` → 库实体名）；「全部书库」视图下 `library_id` 仍可能是具体库。
 * 查不到实体就不返回 —— **不回落 `library_id`**（那是内部 id，行内显示它没有意义），
 * 「书库」那一行随之整行不渲染。与面包屑第二段同一条口径（见 `BookDetailView.libraryName`）。
 */
const libraryName = computed(() => {
  const id = props.book.library_id
  if (!id) return ''
  return library.libraryEntities.find((l) => l.id === id)?.name || ''
})

/**
 * 版本信息区的行（第 30 期补全）：
 * - 书库（归属库，来自 book.library_id）
 * - 入库（单独一行，可编辑；与导出 CSV「入库日期」同源：`added_at` 覆盖 ?? 文件 mtime）
 * - 页数（非 EPUB 恒 0 → 不展示；带来源标注：估算值 / 归档真实值）
 * 移除原先写死「字数：未知」的假值行（项目约定不做假交互）。
 */
const versionRows = computed<Array<{ k: string; v: string; hint?: string }>>(() => {
  const b = props.book
  const rows: Array<{ k: string; v: string; hint?: string }> = []
  rows.push({ k: '系列', v: b.series || '独立作品' })
  if (libraryName.value) rows.push({ k: '书库', v: libraryName.value })
  rows.push({ k: '出版年', v: b.year || '未知' })
  rows.push({ k: '出版社', v: b.publisher || '未知' })
  rows.push({ k: '语言', v: b.language || '未知' })
  rows.push({ k: 'ISBN', v: b.isbn || '未知' })
  if (Array.isArray(b.narrators) && b.narrators.length) {
    rows.push({ k: '演播', v: b.narrators.join('、') })
  }
  if (b.pages && b.pages > 0) {
    const src =
      b.pages_source === 'archive'
        ? '归档真实页数'
        : b.pages_source === 'estimate'
          ? 'EPUB 估算页数'
          : ''
    rows.push({ k: '页数', v: String(b.pages), hint: src })
  }
  return rows
})

// ---------------- 入库时间（第 154 期，可编辑）----------------
const editingAdded = ref(false)
const addedDraft = ref('')
const addedError = ref('')
const addedTs = computed(() => props.book.added_at || props.book.mtime || 0)

function startEditAdded(): void {
  addedError.value = ''
  addedDraft.value = localDate(new Date(addedTs.value * 1000))
  editingAdded.value = true
}

async function saveAdded(): Promise<void> {
  const ts = localDateToEpoch(addedDraft.value)
  if (!ts) {
    addedError.value = '请选择有效日期'
    return
  }
  try {
    await api.setBookAddedAt(props.book.id, ts)
    editingAdded.value = false
    emit('refresh')
  } catch (e) {
    addedError.value = e instanceof Error ? e.message : '保存失败'
  }
}

async function resetAdded(): Promise<void> {
  try {
    await api.setBookAddedAt(props.book.id, null)
    editingAdded.value = false
    emit('refresh')
  } catch (e) {
    addedError.value = e instanceof Error ? e.message : '恢复失败'
  }
}

// ---------------- 封面（第 155 期）----------------
const coverBusy = ref(false)
const coverUrlDraft = ref('')
const coverError = ref('')

async function uploadCover(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  coverBusy.value = true
  coverError.value = ''
  try {
    await api.uploadCover(props.book.id, file)
    emit('refresh')
  } catch (err) {
    coverError.value = err instanceof Error ? err.message : '上传失败'
  } finally {
    coverBusy.value = false
    input.value = ''
  }
}

async function applyCoverUrl(): Promise<void> {
  const url = coverUrlDraft.value.trim()
  if (!url) return
  coverBusy.value = true
  coverError.value = ''
  try {
    await api.coverFromUrl(props.book.id, url)
    coverUrlDraft.value = ''
    emit('refresh')
  } catch (err) {
    coverError.value = err instanceof Error ? err.message : '抓取失败'
  } finally {
    coverBusy.value = false
  }
}

async function removeCover(): Promise<void> {
  coverBusy.value = true
  coverError.value = ''
  try {
    await api.deleteCover(props.book.id)
    emit('refresh')
  } catch (err) {
    coverError.value = err instanceof Error ? err.message : '移除失败'
  } finally {
    coverBusy.value = false
  }
}
</script>

<template>
  <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
    <div class="flex min-w-0 flex-col gap-4 lg:col-span-2">
      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">简介</h3>
        <p
          class="text-[12.5px] leading-relaxed text-muted-foreground"
          :class="descOpen ? '' : 'line-clamp-4'"
        >
          {{ book.description || '暂无简介。' }}
        </p>
        <button
          v-if="book.description && book.description.length > 80"
          type="button"
          class="mt-1.5 cursor-pointer text-[11.5px] text-primary"
          @click="descOpen = !descOpen"
        >
          {{ descOpen ? '收起' : '展开全文' }}
        </button>
      </Card>

      <Card v-if="files.length">
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">成品文件</h3>
        <div class="flex flex-col gap-1.5">
          <div
            v-for="f in files"
            :key="f.name"
            class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
          >
            <span class="text-[11px] font-semibold text-foreground">{{ f.format }}</span>
            <span class="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground">
              {{ fmtSize(f.size) }} · {{ fmtDate(f.mtime) }}
            </span>
            <Button size="sm" @click="emit('download', f.name)">下载</Button>
          </div>
        </div>
      </Card>

      <Card v-if="similar.length">
        <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">相似书</h3>
        <SimilarBooks
          :items="similar"
          :expanded="similarExpanded"
          :preview="SIMILAR_PREVIEW"
          :max="similarMax"
          @expand="emit('expandSimilar')"
          @open="(id) => emit('openBook', id)"
        />
      </Card>
    </div>

    <Card>
      <h3 class="mb-3 text-[13px] font-semibold text-foreground">版本信息</h3>
      <dl class="flex flex-col gap-2.5">
        <div v-for="item in versionRows" :key="item.k" class="flex items-baseline gap-3">
          <dt class="w-[4.5rem] shrink-0 text-[11px] text-muted-foreground">{{ item.k }}</dt>
          <dd class="min-w-0 flex-1 text-[12.5px] break-words text-foreground">
            {{ item.v }}<span v-if="item.hint" class="ml-1 text-[10.5px] text-muted-foreground">{{ item.hint }}</span>
          </dd>
        </div>
      </dl>

      <!-- 入库时间（第 154 期）：单独一行，可改成别的日期或恢复为文件时间 -->
      <div class="mt-3 border-t border-border pt-2.5">
        <div class="flex flex-wrap items-center gap-2 text-[11.5px]">
          <span class="w-[4.5rem] shrink-0 text-muted-foreground">入库</span>
          <template v-if="!editingAdded">
            <span class="tabular-nums text-foreground">{{ addedTs ? fmtDateSlash(addedTs) : '未知' }}</span>
            <button type="button" class="cursor-pointer text-primary hover:underline" @click="startEditAdded">修改</button>
          </template>
          <template v-else>
            <input
              v-model="addedDraft"
              type="date"
              aria-label="入库日期"
              class="h-7 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
            >
            <Button size="sm" variant="primary" @click="saveAdded">保存</Button>
            <Button size="sm" variant="ghost" @click="editingAdded = false">取消</Button>
            <Button size="sm" variant="ghost" @click="resetAdded">恢复为文件时间</Button>
          </template>
        </div>
        <p v-if="addedError" class="mt-1 text-[11px] text-destructive">{{ addedError }}</p>
      </div>
    </Card>

    <!-- 封面（第 155 期）：只存服务端 DB，不写书文件 -->
    <Card class="mt-4">
      <h3 class="mb-2 text-[13px] font-semibold text-foreground">封面</h3>
      <p class="mb-2 text-[11.5px] text-muted-foreground">
        自定义封面只保存在应用数据库，不写回书文件；移除后回退内嵌封面或渐变占位。
      </p>
      <div class="flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          aria-label="上传封面"
          class="max-w-[12rem] text-[11.5px] text-muted-foreground file:mr-2 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-muted file:px-2 file:py-1 file:text-[11.5px] file:text-foreground"
          :disabled="coverBusy"
          @change="uploadCover"
        >
        <input
          v-model="coverUrlDraft"
          type="url"
          aria-label="封面 URL"
          placeholder="https://…"
          class="h-7 min-w-[10rem] flex-1 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
          :disabled="coverBusy"
          @keyup.enter="applyCoverUrl"
        >
        <Button size="sm" variant="secondary" :disabled="coverBusy || !coverUrlDraft.trim()" @click="applyCoverUrl">
          从 URL 应用
        </Button>
        <Button size="sm" variant="ghost" :disabled="coverBusy" @click="removeCover">
          移除服务端封面
        </Button>
      </div>
      <p v-if="coverError" class="mt-1 text-[11px] text-destructive">{{ coverError }}</p>
    </Card>
  </div>
</template>
