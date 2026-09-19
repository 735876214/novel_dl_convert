<script setup lang="ts">
/**
 * 重排系列序号（第 12 期 C3）。
 *
 * 关键约束（决定了这个对话框为什么要写成「先预览、再应用」）：
 *  · 序号只写**服务端**（`meta_override.series_index`），
 *    **不动文件名、也不改写 EPUB 文件** ——
 *    文件名是 book_id 的来源，文件名不动则 book_id 不变，
 *    阅读进度 / 批注 / 评分 / 收藏**不会断链**；
 *  · 逐册可调：默认按当前序号升序编号 1..N，缺序号的排在最后（不假装它是第一册），
 *    可以上下移动或直接改数字；
 *  · 应用前必须先看到预览（没拉到预览时确认按钮保持禁用）。
 */
import { computed, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import { api, type SeriesRenumberItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ name: string; open: boolean }>()
const emit = defineEmits<{ close: []; applied: [] }>()

const ui = useUiStore()
const rows = ref<Array<{ item: SeriesRenumberItem; idx: string }>>([])
const loading = ref(false)
const busy = ref(false)
const result = ref<{ renumbered: number; skipped: Array<{ name: string; error: string }> } | null>(null)

const changedCount = computed(
  () => rows.value.filter((r) => r.idx.trim() !== r.item.old_index).length,
)

async function load(): Promise<void> {
  loading.value = true
  result.value = null
  try {
    const res = await api.seriesRenumberPreview(props.name)
    rows.value = res.items.map((item) => ({ item, idx: item.new_index }))
  } catch (e) {
    rows.value = []
    ui.toast(e instanceof Error ? e.message : '预览失败')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (v) => {
    if (v) void load()
  },
)

/** 上下移动后按新顺序**重新连续编号** —— 否则会出现 1,3,2 这种空洞，反而更难读 */
function move(index: number, delta: number): void {
  const next = index + delta
  if (next < 0 || next >= rows.value.length) return
  const arr = [...rows.value]
  const [picked] = arr.splice(index, 1)
  arr.splice(next, 0, picked)
  rows.value = arr.map((r, i) => ({ ...r, idx: String(i + 1) }))
}

async function apply(): Promise<void> {
  busy.value = true
  try {
    const res = await api.seriesRenumberApply(
      props.name,
      rows.value.map((r) => ({ name: r.item.name, new_index: r.idx.trim() })),
    )
    result.value = { renumbered: res.renumbered, skipped: res.skipped ?? [] }
    ui.toast(`已重排 ${res.renumbered} 册`)
    emit('applied')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '重排失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="open" class="fixed inset-0 z-[70] grid place-items-center bg-black/45 p-4">
    <div class="w-[min(46rem,94vw)] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl">
      <h3 class="font-serif text-[17px] font-semibold text-foreground">重排系列序号</h3>
      <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
        序号存进应用数据库（<strong>不改写 EPUB 文件、也不改文件名</strong>）——
        因此阅读进度、批注、评分与收藏都不会断链，可以随时再排或还原。
        清空某一册的数字 = 这一册没有序号（同样只存服务端；用别的软件直读文件时看不到）。
      </p>

      <div v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">
        正在读取当前顺序…
      </div>

      <template v-else>
        <div class="mt-3 flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <span>共 {{ rows.length }} 册</span>
          <span v-if="changedCount">· {{ changedCount }} 册的序号会发生变化</span>
          <span v-else>· 当前顺序已连续，无需改动</span>
        </div>

        <!-- 左：当前顺序（只读）；右：新序号（可改 / 可上下移动） -->
        <div class="mt-2 divide-y divide-border/60 rounded-md border border-border">
          <div
            v-for="(r, i) in rows"
            :key="r.item.name"
            class="flex flex-wrap items-center gap-2 px-3 py-2"
          >
            <span class="w-6 text-right font-mono text-[11px] text-muted-foreground">{{ i + 1 }}</span>
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground" :title="r.item.name">
              {{ r.item.title }}
            </span>
            <span class="font-mono text-[11px] text-muted-foreground">
              原 {{ r.item.old_index || '无序号' }}
            </span>
            <input
              v-model="r.idx"
              type="text"
              inputmode="numeric"
              class="h-7 w-14 rounded-md border border-border bg-muted px-2 text-center font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
            >
            <button
              type="button"
              class="cursor-pointer rounded px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
              :disabled="i === 0"
              title="上移"
              @click="move(i, -1)"
            >
              ↑
            </button>
            <button
              type="button"
              class="cursor-pointer rounded px-1 text-[12px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
              :disabled="i === rows.length - 1"
              title="下移"
              @click="move(i, 1)"
            >
              ↓
            </button>
          </div>
        </div>

        <!-- 结果：逐条成功 / 跳过原因（跳过不藏起来，用户要知道哪条没生效） -->
        <div v-if="result" class="mt-3 rounded-md border border-border px-3 py-2 text-[12px]">
          <div class="text-foreground">已重排 {{ result.renumbered }} 册</div>
          <ul v-if="result.skipped.length" class="mt-1 space-y-0.5 text-muted-foreground">
            <li v-for="s in result.skipped" :key="s.name">{{ s.name }}：{{ s.error }}</li>
          </ul>
        </div>

        <div class="mt-4 flex items-center gap-2">
          <Button
            size="sm"
            variant="primary"
            :disabled="busy || loading || !rows.length || !changedCount"
            @click="apply"
          >
            {{ busy ? '执行中…' : '确认执行' }}
          </Button>
          <Button size="sm" variant="ghost" :disabled="busy" @click="emit('close')">关闭</Button>
          <span v-if="!changedCount" class="text-[11px] text-muted-foreground">
            没有变化时不写文件
          </span>
        </div>
      </template>
    </div>
  </div>
</template>
