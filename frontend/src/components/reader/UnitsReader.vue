<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import AudioPlayer from '@/components/reader/AudioPlayer.vue'
import ComicReader from '@/components/reader/ComicReader.vue'
import PdfReader from '@/components/reader/PdfReader.vue'
import { api, type UnitItem, type UnitPos, type UnitRef } from '@/lib/api'
import { fromPercent, toPercent } from '@/lib/unitsProgress'
import { useLibraryStore } from '@/stores/library'

/**
 * **序号单元合集阅读器**（第 73 期）。
 *
 * 「一棵树 = 一本书」的目录（`根目录/《书名》/第1卷/第1话.pdf`…）扫描后是一本书
 * （`format === 'UNITS'`，话清单见 `core/units.py`）。阅读形态是**逐话连续读**：
 * 左边话目录、工具栏上/下一话、读完自动续下一话、进度跨话连续。
 *
 * ## 进度：上层独占
 *
 * 整本书只有 `progress` 那一行 `percent`（**零新列、零迁移**），它编码的是
 * 「第几话 + 这一话内多少」（算式见 `lib/unitsProgress.ts`，唯一真值源）。
 *
 * 于是本组件是**唯一写进度的地方**，三个复用的子阅读器（PDF / 漫画 / 音频）拿到
 * `unit` 后只上报「这一话读到哪」，不读也不写。这不是洁癖：子组件各写一半必然互相
 * 覆盖 —— 换话时旧话那个组件会先卸载，它的收尾上报会把进度写回**旧话**。
 * 上报载荷带 `index`，本组件据此丢弃过期上报（见 `api.UnitPos`）。
 *
 * ## 进度恢复
 *
 * 进阅读器时读一次书级 percent ⇒ 反推出「第几话 + 话内比例」，交给子阅读器自己去
 * 换算成页码 / 秒数（所以本组件不需要知道这一话有多少页）。**读一次就够了**：
 * 阅读期间位置由本组件独占，不存在「别处改了要跟着跳」的问题（多设备提示只长在
 * 章节流阅读器里，见 ReaderView 的说明）。
 */
const props = defineProps<{
  bookId: string
  title: string
  /** 所属系列名：**末话**读完后的「自动翻下一册」用它（书内换话不走系列） */
  series?: string
  /** 话清单（随详情下发，见 `library.book_detail`） */
  units: UnitItem[]
}>()

const router = useRouter()
const library = useLibraryStore()

const total = computed(() => props.units.length)
const index = ref(0)
/** 这一话读到哪（0–1，**话内**坐标）；由子阅读器上报 */
const within = ref(0)
/** 这一话内的位置（音频 = 秒数 / 漫画与 PDF = 页号 0 起）：只作为 `progress.locator` 落库 */
const locator = ref(0)
/** 恢复完成前不渲染子阅读器：否则它会从这一话的开头开始，恢复结果到了再跳一下 */
const ready = ref(false)
const showToc = ref(true)
/** 上一话放完自动续过来：下一话的音频自动开播（用户点目录换话时不自动播） */
const autoplayNext = ref(false)

const current = computed<UnitItem | null>(() => props.units[index.value] ?? null)

/**
 * 交给子阅读器的「当前话」。`index` 是话的**位置**（0 起），它同时是 `/units/{index}`
 * 这个路径参数、也是 percent 的坐标 —— 服务端话清单的 `index` 与位置逐字相同
 * （见 `core/units.units` 的排序），所以两边不用换算。
 */
const unitRef = computed<UnitRef | null>(() => (current.value
  ? {
      index: current.value.index,
      total: total.value,
      name: current.value.name,
      within: within.value,
    }
  : null))

/** 话的种类 → 用哪个阅读器 + 界面上如实标注的徽章文案 */
const KIND_LABELS: Record<string, string> = { pdf: 'PDF', comic: '漫画', audio: '音频' }
const kindLabel = (k: string): string => KIND_LABELS[k] ?? k.toUpperCase()

// ---------------- 进度：写在本组件 ----------------

/**
 * 落盘。**不做去抖、也不四舍五入**：
 * - 去抖没有必要 —— 子阅读器已经在各自的节奏上报（音频每 5 秒、漫画翻页 / 滚动 600ms），
 *   本组件再压一层只会让「退出时最后一段没写进去」；
 * - 四舍五入会把话内精度抹掉：43 话的书里 1 话只占 2.3%，整成整数百分比后
 *   「第 3 话读了 40%」与「第 3 话读了 90%」会落成同一个数（`percent` 列是 REAL）。
 */
function save(): Promise<void> {
  const pct = toPercent(index.value, within.value, total.value)
  return api.setProgress(props.bookId, locator.value, pct)
    .then((r) => {
      // 进度就地回写 store（首页「继续阅读」实时）
      library.patchProgress(props.bookId, pct, r?.updated_at)
    })
    .catch(() => { /* 离线或未登录：静默，不打断阅读 */ })
}

/** 子阅读器的进度上报（话内）。**过期的丢掉** —— 见文件头的说明 */
function onUnitPos(p: UnitPos): void {
  if (p.index !== index.value) return
  within.value = p.within
  locator.value = p.locator
  void save()
}

/** 这一话读完了、书里还有下一话 ⇒ 换话（并让下一话的音频自动接着放） */
function onUnitEnd(): void {
  void goUnit(index.value + 1, true)
}

/**
 * 换到第 `i` 话。
 *
 * 两笔写入是**串行**的（旧话的收尾 → 新话的开头）：并发发出去的话，服务端两次
 * 写入谁后落谁赢，而读点会因此停在一个旧位置上。中间那次 `await` 保证顺序。
 */
async function goUnit(i: number, autoplay = false): Promise<void> {
  if (i < 0 || i >= total.value || i === index.value) return
  await save()                    // 先把旧话读到的位置落盘
  index.value = i
  within.value = 0
  locator.value = 0
  autoplayNext.value = autoplay
  await save()                    // 新话立刻记成「读到开头」：换话后马上去别的页面也不丢
}

onMounted(async () => {
  try {
    const p = await api.getProgress(props.bookId)
    if (p && p.percent > 0) {
      const r = fromPercent(p.percent, total.value)
      index.value = r.index
      within.value = r.within
    }
  } catch {
    /* 无进度 / 离线：从第一话开头开始 */
  }
  ready.value = true
})

onBeforeUnmount(() => {
  // 离开阅读器时把当前位置补写一次：子阅读器的最后一次上报可能已经隔了几秒
  void save()
})
</script>

<template>
  <div class="flex h-full min-h-0 flex-col">
    <!-- 工具栏 -->
    <div class="flex flex-wrap items-center gap-2 border-b border-border pb-2">
      <Button size="sm" variant="ghost" title="返回详情" @click="router.push(`/book/${props.bookId}`)">
        <Icon name="arrowLeft" class="h-4 w-4" />
      </Button>
      <Button size="sm" variant="ghost" title="话目录" @click="showToc = !showToc">
        <Icon name="book" class="h-4 w-4" />
      </Button>
      <div class="min-w-0 flex-1">
        <div class="truncate text-[12px] text-muted-foreground">{{ props.title }}</div>
        <div class="truncate text-[13px] font-medium text-foreground">
          {{ current?.name || '（没有可读的话）' }}
        </div>
      </div>

      <Button size="sm" variant="ghost" title="上一话" :disabled="index <= 0" @click="goUnit(index - 1)">
        <Icon name="arrowLeft" class="h-3.5 w-3.5" />
      </Button>
      <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ total ? index + 1 : 0 }} / {{ total }}</span>
      <Button
        size="sm"
        variant="ghost"
        title="下一话"
        :disabled="index >= total - 1"
        @click="goUnit(index + 1)"
      >
        <Icon name="arrowRight" class="h-3.5 w-3.5" />
      </Button>
      <span v-if="current" class="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10.5px] text-muted-foreground">
        {{ kindLabel(current.kind) }}
      </span>
    </div>

    <div v-if="!total" class="py-20 text-center text-[13px] text-muted-foreground">
      这本合集里没有可读的话（目录里没有能识别出序号的媒体文件）。
    </div>

    <div v-else class="relative flex min-h-0 flex-1">
      <!-- 话目录 -->
      <aside v-if="showToc" class="w-60 shrink-0 overflow-y-auto border-r border-border py-2 pr-2">
        <button
          v-for="u in props.units"
          :key="u.index"
          type="button"
          class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-left text-[12.5px] transition-colors"
          :class="u.index === index ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
          :title="u.name"
          @click="goUnit(u.index)"
        >
          <span class="w-7 shrink-0 text-center text-[10.5px] tabular-nums">{{ u.index + 1 }}</span>
          <span class="truncate">{{ u.name }}</span>
        </button>
      </aside>

      <div v-if="!ready" class="flex-1 py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

      <!-- 主区：按这一话的种类交给对应的阅读器。`:key` 让换话时**重建** ——
           三个阅读器都持有「当前文件」的内部状态（PDF 文档句柄 / 页清单 / 音频元素），
           复用实例会让它们接着读上一话的内容 -->
      <template v-else-if="current">
        <div v-if="current.kind === 'audio'" class="min-w-0 flex-1 overflow-y-auto p-4">
          <AudioPlayer
            :key="current.index"
            :book-id="props.bookId"
            :tracks="[]"
            :series="props.series"
            :unit="unitRef"
            :autoplay="autoplayNext"
            @unit-pos="onUnitPos"
            @unit-end="onUnitEnd"
          />
        </div>
        <div v-else class="flex min-h-0 min-w-0 flex-1 flex-col">
          <PdfReader
            v-if="current.kind === 'pdf'"
            :key="current.index"
            :book-id="props.bookId"
            :title="current.name"
            :series="props.series"
            :unit="unitRef"
            @unit-pos="onUnitPos"
            @unit-end="onUnitEnd"
          />
          <ComicReader
            v-else
            :key="current.index"
            :book-id="props.bookId"
            :title="current.name"
            :series="props.series"
            source="archive"
            :unit="unitRef"
            @unit-pos="onUnitPos"
            @unit-end="onUnitEnd"
          />
        </div>
      </template>
    </div>
  </div>
</template>
