<script setup lang="ts">
/**
 * 跨库移动（第 36 期 T4）：书架上选好几本 → 挑一个目标库 → 看逐本预检 → 真搬。
 *
 * 三段式，因为这三件事各自都会拦住人：
 *
 * 1. **选目标库**：只有**类型相容**的库可选。不相容的不是「不方便」而是「搬过去就没了」——
 *    库扫描白名单决定文件在那个库里根本不出现在书目中（不是半可见）。所以这里把不相容的
 *    库**逐条列出并写明原因**（而不是从列表里悄悄抹掉：用户会以为库没建好）。
 *    真正不许发生的事由后端 `/plan` 翻 400 拦，前端禁选只是别让人白点一次。
 * 2. **预检清单**：逐本说清「能搬 / 撞名 / 搬不了」。撞名的逐条给动作（用建议名移入 / 跳过），
 *    搬不了的如实列出来但**不掺进本次搬运**。
 * 3. **确认**：只报真数字（将移动 N 本、其中 M 本副本随迁），不写「预计」「约」。
 *
 * 移动**只挪库不改内容**：进度 / 批注 / 元数据 / 封面随书走，副本（成品目录里那份）
 * 也一起搬；目标库没配成品目录时副本留在原库，这里提前说出来。
 */
import { computed, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  api,
  type BookMoveDecision,
  type BookMovePreview,
  type BookMoveTarget,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{
  open: boolean
  /** 要移动的书 id（书架上当前选中的那些） */
  bookIds: string[]
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'moved', taskId: string): void }>()

const ui = useUiStore()
const library = useLibraryStore()

const targets = ref<BookMoveTarget[]>([])
const dstId = ref('')
const preview = ref<BookMovePreview | null>(null)
/** 冲突条目的处置：book_id → 动作（默认 move = 不处理，冲突即不搬进本次） */
const decisions = ref<Record<string, 'rename' | 'skip'>>({})
const busy = ref('')
const loading = ref(false)

/** 可选（相容）的库；「书已经在这个库里」的不在其中 */
const usable = computed(() => targets.value.filter((t) => t.compatible && !t.same_as_source))
const blockedTargets = computed(() =>
  targets.value.filter((t) => !t.compatible || t.same_as_source),
)
const dst = computed(() => targets.value.find((t) => t.id === dstId.value) ?? null)

/** 冲突条目：给动作的那几条 */
const conflicts = computed(() => (preview.value?.items ?? []).filter((i) => i.status === 'conflict'))
const blockedItems = computed(() => (preview.value?.items ?? []).filter((i) => i.status === 'blocked'))
const readyItems = computed(() => (preview.value?.items ?? []).filter((i) => i.status === 'ready'))

/** 交给后端的处置清单（未表态的冲突条目**不传**，后端口径就是「冲突即不搬」） */
function decisionList(): BookMoveDecision[] {
  return Object.entries(decisions.value).map(([id, action]) =>
    action === 'rename'
      ? { id, action, new_name: conflicts.value.find((c) => c.book_id === id)?.suggest ?? '' }
      : { id, action },
  )
}

async function loadTargets(): Promise<void> {
  loading.value = true
  preview.value = null
  decisions.value = {}
  dstId.value = ''
  try {
    const r = await api.bookMoveTargets(props.bookIds)
    targets.value = r.items
    if (!r.total_books && r.message) ui.toast(r.message)
    // 只有一个可选项时直接选上（少一次点击；多选时留空让人自己挑）
    if (usable.value.length === 1) dstId.value = usable.value[0].id
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读不到可选书库')
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.bookIds.join(',')],
  () => {
    if (props.open) void loadTargets()
  },
  { immediate: true },
)

/** 换库 / 改处置都要重算预检 —— 预检是只读的，随便刷 */
async function refresh(): Promise<void> {
  if (!dstId.value) {
    preview.value = null
    return
  }
  try {
    preview.value = await api.bookMovePreflight(props.bookIds, dstId.value, decisionList())
  } catch (e) {
    preview.value = null
    ui.toast(e instanceof Error ? e.message : '预检失败')
  }
}

watch(dstId, () => void refresh())

function setDecision(id: string, action: 'rename' | 'skip'): void {
  decisions.value = { ...decisions.value, [id]: action }
  void refresh()
}

const COPY_LABEL: Record<string, string> = {
  none: '没有副本',
  left: '副本留在原库',
  same: '副本已在目标库',
  reuse: '副本已在目标库',
  move: '副本随迁',
}

function copyLabel(i: { copy: { action: string } }): string {
  return COPY_LABEL[i.copy.action] ?? i.copy.action
}

async function submit(): Promise<void> {
  if (!dstId.value) {
    ui.toast('先选一个目标书库')
    return
  }
  busy.value = 'plan'
  try {
    const planned = await api.bookMovePlan(props.bookIds, dstId.value, decisionList())
    if (!planned.batch_id) {
      ui.toast(planned.message || '没有可移动的条目')
      return
    }
    const r = await api.bookMoveApply(planned.batch_id)
    // 进度在任务中心看：这里只说「已经开始了」，不编造搬了几本
    ui.toast(`开始移动 ${planned.created} 本，进度见任务中心`)
    emit('moved', r.task_id)
    emit('close')
  } catch (e) {
    // 后端 400 的那句就是真原因（相容闸门 / 目标库不存在），原样显示
    ui.toast(e instanceof Error ? e.message : '移动失败')
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
    @click.self="emit('close')"
  >
    <div
      class="w-[min(44rem,94vw)] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl"
    >
      <div class="flex items-start gap-2">
        <h3 class="font-serif text-[17px] font-semibold text-foreground">移动到书库</h3>
        <span class="mt-1 text-[11.5px] text-muted-foreground">已选 {{ bookIds.length }} 本</span>
        <Button size="sm" variant="ghost" class="ml-auto" @click="emit('close')">关闭</Button>
      </div>
      <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
        移动只<strong>挪库、不改内容</strong>：阅读进度、批注、评分与元数据随书走，
        成品目录里的副本也一起搬。目标库已有同名文件时一律拒绝覆盖。
      </p>

      <!-- ① 目标库：不相容的照列 + 写明原因 -->
      <div class="mt-4 text-[12.5px] font-medium text-foreground">移到哪个库</div>
      <p v-if="loading" class="mt-1 text-[12px] text-muted-foreground">读取书库中…</p>
      <template v-else>
        <div v-if="usable.length" class="mt-2 flex flex-wrap gap-2">
          <button
            v-for="t in usable"
            :key="t.id"
            type="button"
            class="rounded-md border px-2.5 py-1.5 text-left text-[12px] transition-colors"
            :class="
              dstId === t.id
                ? 'border-primary bg-primary/10 text-foreground'
                : 'border-border text-muted-foreground hover:border-primary/60'
            "
            :disabled="!!busy"
            @click="dstId = t.id"
          >
            <span class="font-medium">{{ t.name }}</span>
            <span class="ml-1 opacity-70">{{ t.type_label }}</span>
            <span v-if="!t.publish_configured" class="ml-1 text-[11px] opacity-70">· 无成品目录</span>
          </button>
        </div>
        <p v-else class="mt-2 text-[12px] text-muted-foreground">
          没有能接收这批书的库 —— 见下面的原因。
        </p>

        <!-- 禁选项照列：抹掉的话用户会以为库没建好 -->
        <div v-if="blockedTargets.length" class="mt-2 space-y-1">
          <div
            v-for="t in blockedTargets"
            :key="t.id"
            class="rounded-md border border-border/60 px-2.5 py-1.5 text-[11.5px] text-muted-foreground"
          >
            <span class="text-foreground/70">{{ t.name }}</span>
            <span class="ml-1 opacity-70">{{ t.type_label }}</span>
            <span class="ml-1">
              ·
              {{
                t.same_as_source
                  ? '书已经在其中'
                  : `有 ${t.blocked_count} 本进不去：${t.reason}`
              }}
            </span>
          </div>
        </div>
      </template>

      <!-- ② 预检清单 -->
      <template v-if="preview">
        <div class="mt-4 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
          <span class="font-medium text-foreground">预检</span>
          <span>可移动 <b class="text-foreground tabular-nums">{{ preview.movable }}</b> 本</span>
          <span v-if="preview.conflict">· 撞名 {{ preview.conflict }}</span>
          <span v-if="preview.blocked">· 搬不了 {{ preview.blocked }}</span>
          <Button size="sm" variant="ghost" class="ml-auto" @click="refresh">重新预检</Button>
        </div>

        <!-- 撞名：逐条给动作。默认不动 → 这一本不进本次搬运（不替用户决定） -->
        <div v-if="conflicts.length" class="mt-2 space-y-1">
          <div
            v-for="c in conflicts"
            :key="c.book_id"
            class="rounded-md border border-border p-2.5"
          >
            <div class="text-[12px] text-foreground">
              <span class="font-medium">{{ c.name }}</span>
              <span class="ml-2 text-muted-foreground">{{ c.reason }}</span>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                :variant="decisions[c.book_id] === 'rename' ? 'primary' : 'ghost'"
                :disabled="!!busy"
                @click="setDecision(c.book_id, 'rename')"
              >
                用建议名移入（{{ c.suggest }}）
              </Button>
              <Button
                size="sm"
                :variant="decisions[c.book_id] === 'skip' ? 'primary' : 'ghost'"
                :disabled="!!busy"
                @click="setDecision(c.book_id, 'skip')"
              >
                跳过这本
              </Button>
              <span v-if="!decisions[c.book_id]" class="text-[11.5px] text-muted-foreground">
                不选则本次不搬
              </span>
            </div>
          </div>
        </div>

        <!-- 搬不了的：如实列出，不掺进本次 -->
        <div v-if="blockedItems.length" class="mt-2 space-y-1">
          <div
            v-for="b in blockedItems"
            :key="b.book_id"
            class="flex items-start gap-2 rounded-md border border-border/60 p-2 text-[11.5px] text-muted-foreground"
          >
            <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span><span class="text-foreground/80">{{ b.name }}</span> · {{ b.reason }}</span>
          </div>
        </div>

        <!-- 会动的那些（含副本去向）——只列真会搬的，避免「列了一堆其实不动」 -->
        <div v-if="readyItems.length" class="mt-2 max-h-52 space-y-1 overflow-y-auto">
          <div
            v-for="i in readyItems"
            :key="i.book_id"
            class="flex items-center gap-2 rounded-md border border-border/60 px-2.5 py-1 text-[11.5px]"
          >
            <span class="min-w-0 flex-1 truncate text-foreground/90">{{ i.name }}</span>
            <span class="shrink-0 text-muted-foreground">{{ copyLabel(i) }}</span>
          </div>
        </div>

        <div class="mt-3 rounded-md border border-border p-2.5 text-[12px] text-foreground">
          将移动 <b class="tabular-nums">{{ preview.will_move_files }}</b> 本<template
            v-if="preview.will_move_copies"
          >，其中 <b class="tabular-nums">{{ preview.will_move_copies }}</b> 本副本随迁</template>
          <template v-if="preview.dst_library_name">
            → 「{{ preview.dst_library_name }}」
          </template>
        </div>
      </template>

      <div class="mt-4 flex items-center gap-2">
        <Button
          size="sm"
          variant="primary"
          :disabled="!!busy || !dstId || !preview || preview.will_move_files === 0"
          @click="submit"
        >
          {{ busy === 'plan' ? '移动中…' : '开始移动' }}
        </Button>
        <span class="text-[11.5px] text-muted-foreground">
          移动在后台跑，每本一条进度；搬完可在书架上「撤销本次移动」。
        </span>
      </div>
    </div>
  </div>
</template>
