<script setup lang="ts">
import { computed, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SimilarBooks from '@/components/book/detail/SimilarBooks.vue'
import type { BookCard, BookFile, SimilarBook } from '@/lib/api'
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
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
 * - 入库（与导出 CSV「入库日期」同源：都是文件 mtime）
 * - 页数（非 EPUB 恒 0 → 不展示；带来源标注：估算值 / 归档真实值）
 * 移除原先写死「字数：未知」的假值行（项目约定不做假交互）。
 */
const versionRows = computed<Array<{ k: string; v: string; hint?: string }>>(() => {
  const b = props.book
  const rows: Array<{ k: string; v: string; hint?: string }> = []
  rows.push({ k: '系列', v: b.series || '独立作品' })
  if (libraryName.value) rows.push({ k: '书库', v: libraryName.value })
  if (b.mtime) rows.push({ k: '入库', v: fmtDateSlash(b.mtime) })
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
    </Card>
  </div>
</template>
