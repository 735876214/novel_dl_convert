<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type BookCard, type BookDetail } from '@/lib/api'
import { formatLabel, seriesIndexLabel, tagsLabel } from '@/lib/bookInfo'
import { isAudioBook, openTargetOf } from '@/lib/bookOpen'
import { fmtBytes } from '@/lib/format'
import { statusLabelOf } from '@/lib/readingThresholds'
import { useLibraryStore } from '@/stores/library'

/**
 * 快速预览浮层（第 64 期）。
 *
 * 居中的小弹窗而不是抽屉：仓库里零抽屉先例，而居中弹窗有现成骨架
 *（`BookMoveDialog.vue` / `ExploreView.vue` 的预览弹窗，类串与关闭按钮逐字同款）。
 *
 * ## 内容**基本取自书卡**，详情请求补两项
 *
 * 封面 / 书名 / 作者 / 系列 / 格式 / 大小 / 状态 / 进度都在 `BookCard` 上
 *（书架已经加载好了），所以这个浮层**打开即有内容、不发请求也是完整的**。
 * 详情请求（`GET /api/books/{bid}`，`library.getBookDetail` 缓存优先）补两项：
 * **章节数**（卡片上没有、又确实属于「预览」），以及 **简介正文** ——
 * 第 68 期起列表接口不再下发简介（它曾占列表体积的 68%），正文只在详情里。
 *
 * 因此失败处理也就不一样：详情拉不到时，**不把整块内容换成错误页**（那会把一份
 * 真数据说成「没有」），只在那一行位置说清「详细目录没拿到」并给一个重试。
 *
 * ## 刻意**不给**的东西
 *
 * 批注、阅读日志、文件绝对路径、任何编辑入口 —— 那是详情页的活。预览是「看一眼
 * 要不要打开」，塞进半页功能就变成了第二个详情页。
 */
const props = defineProps<{ open: boolean; book: BookCard | null }>()
const emit = defineEmits<{
  (e: 'close'): void
  /**
   * 「详细信息」。**把书一起带出去**：父组件不必去猜浮层里现在是谁 ——
   * 那个 props 由 `v-if` 收窄，只有这里能一眼看出它与渲染的内容同源。
   */
  (e: 'open-detail', book: BookCard): void
}>()

const library = useLibraryStore()
const router = useRouter()

const detail = ref<BookDetail | null>(null)
const detailError = ref('')
const loading = ref(false)

const target = computed(() => (props.book ? openTargetOf(props.book) : null))
const canDownload = computed(() => !!props.book && !isAudioBook(props.book) && !!props.book.name)

const chapterCount = computed(() =>
  (detail.value?.chapters ?? []).reduce((s, v) => s + v.chapters.length, 0),
)

/** 简介取**详情**（第 68 期：列表接口不再下发正文）；详情没回来就不渲染这一块 */
const description = computed(() => (detail.value?.description ?? '').trim())

/** 状态与进度一行。状态走 `readingThresholds`（**不在浮层里另写一套文案**） */
const statusLine = computed(() => {
  const b = props.book
  if (!b) return ''
  const s = statusLabelOf(b, b.library_id)
  const p = Math.round(b.percent ?? 0)
  if (p > 0) return `${s} · 已读 ${p}%`
  return s
})

async function load(): Promise<void> {
  const b = props.book
  if (!props.open || !b) return
  loading.value = true
  detailError.value = ''
  const d = await library.getBookDetail(b.id)
  // 取数是异步的：回来时用户可能已经关了浮层、或换到了另一本（竞态）
  if (!props.open || props.book?.id !== b.id) return
  detail.value = d
  if (!d) detailError.value = library.detailError || '加载失败'
  loading.value = false
}

watch(
  () => [props.open, props.book?.id] as const,
  () => {
    if (!props.open) {
      // 关掉就把上一次的状态清干净：否则下一次打开会先闪一眼上一本的章节数
      detail.value = null
      detailError.value = ''
      return
    }
    void load()
  },
  { immediate: true },
)

/** 下载主文件：与详情页 hero 的按钮同款（文件名取路径最后一段，见那里注释） */
function download(): void {
  const b = props.book
  if (!b) return
  const a = document.createElement('a')
  a.href = api.downloadUrl(b.name, b.library_id)
  a.download = b.name.split('/').pop() || b.name
  a.click()
}

/** 从浮层直接开读 / 开听：先关浮层再跳（跳过去之后它就没有存在意义了） */
function startReading(): void {
  const t = target.value
  if (!t) return
  emit('close')
  void router.push(t.to)
}

function openDetail(): void {
  const b = props.book
  if (!b) return
  emit('open-detail', b)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.open) emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div
    v-if="open && book"
    class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
    role="dialog"
    aria-modal="true"
    aria-labelledby="book-preview-title"
    @click.self="emit('close')"
  >
    <div
      class="w-[min(40rem,94vw)] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl"
    >
      <div class="mb-4 flex items-start gap-2">
        <h3 id="book-preview-title" class="min-w-0 flex-1 font-serif text-[16px] font-semibold text-foreground">
          {{ book.title || book.name }}
        </h3>
        <button
          type="button"
          class="grid h-6 w-6 shrink-0 cursor-pointer place-items-center rounded-sm text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="关闭预览"
          @click="emit('close')"
        >
          <Icon name="x" class="h-3.5 w-3.5" />
        </button>
      </div>

      <div class="flex items-start gap-4">
        <div class="w-24 shrink-0 sm:w-28">
          <BookCover :book="book" :show-title="false" :interactive="false" />
        </div>
        <div class="min-w-0 flex-1 text-[12.5px] text-muted-foreground">
          <div class="truncate text-[13px] font-medium text-foreground">
            {{ book.author || '未知作者' }}
          </div>
          <div v-if="book.series" class="mt-1 truncate">
            {{ book.series }}
            <span v-if="seriesIndexLabel(book)" class="ml-1 font-mono text-[11px]">
              {{ seriesIndexLabel(book) }}
            </span>
          </div>
          <div class="mt-1">
            {{ formatLabel(book) }}
            <span v-if="book.size"> · {{ fmtBytes(book.size) }}</span>
            <!-- 章节数是详情补的：拿不到就整段不写（不写「0 章」——那是错信息） -->
            <span v-if="chapterCount > 0"> · {{ chapterCount }} 章</span>
          </div>
          <div v-if="statusLine" class="mt-1">{{ statusLine }}</div>
          <div v-if="tagsLabel(book, 4)" class="mt-1 truncate">{{ tagsLabel(book, 4) }}</div>

          <!--
            详情拉失败：只说清**这一项**没拿到，不把上面的真数据一起吞掉。
            `loading` 期间不显示 —— 那是「正在拿」，不是「没拿到」。
          -->
          <div v-if="detailError && !loading" class="mt-1.5 flex items-center gap-1.5">
            <span class="text-destructive">详细目录没拿到：{{ detailError }}</span>
            <button
              type="button"
              class="cursor-pointer text-primary underline-offset-2 hover:underline"
              @click="load"
            >
              重试
            </button>
          </div>
        </div>
      </div>

      <!-- 没简介就整块不渲染（先例：BookDetailView 的概览简介块）。
           简介来自**详情**（第 68 期起列表不发正文 ⇒ 打开瞬间可能还没有，回来再出现）。 -->
      <p
        v-if="description"
        class="mt-4 line-clamp-4 text-[12.5px] leading-relaxed text-muted-foreground"
      >
        {{ description }}
      </p>

      <div class="mt-5 flex flex-wrap items-center gap-2">
        <Button v-if="target" variant="primary" size="sm" @click="startReading">
          <Icon :name="target.label === '收听' ? 'volume' : 'book'" class="h-3.5 w-3.5" />
          {{ target.label }}
        </Button>
        <Button v-if="canDownload" size="sm" @click="download">
          <Icon name="download" class="h-3.5 w-3.5" />
          下载
        </Button>
        <Button size="sm" class="ml-auto" @click="openDetail">
          详细信息
        </Button>
      </div>
    </div>
  </div>
</template>
