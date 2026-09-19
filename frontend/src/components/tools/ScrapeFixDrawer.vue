<script setup lang="ts">
/**
 * 刮削手动整理抽屉（右侧滑入，第 18 期）。
 *
 * 只解决一件事：**这本书的元数据不对，我要改对，并让外部阅读器立刻看到**。
 * 因此流程被压成两步，顺序固定、界面直说：
 *   ① 改字段（或采用在线候选）→ 写服务端元数据（`meta_override` / `meta_cover`）
 *   ② 应用并重建 → 用同一份生效值重写**副本**（原文件永远不动）
 *
 * 两个刻意的取舍：
 * · 候选抓取（外呼）**只在用户点按钮时**发生 —— 打开抽屉不自动外呼；
 * · 「应用并重建」把两步合成一次点击，避免用户以为「保存了但外部阅读器没变」。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  api,
  type BookMetadata,
  type BookMetadataFields,
  type MetadataPlanItem,
  type ScrapeItem,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ item: ScrapeItem }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'applied'): void }>()

const ui = useUiStore()

type FieldKey = keyof BookMetadataFields

const FIELDS: Array<{ key: FieldKey; label: string; multiline?: boolean }> = [
  { key: 'title', label: '书名' },
  { key: 'author', label: '作者' },
  { key: 'series', label: '系列' },
  { key: 'series_index', label: '卷号' },
  { key: 'date', label: '出版年' },
  { key: 'publisher', label: '出版社' },
  { key: 'language', label: '语言' },
  { key: 'isbn', label: 'ISBN' },
  { key: 'tags', label: '题材（、分隔）' },
  { key: 'description', label: '简介', multiline: true },
]

const meta = ref<BookMetadata | null>(null)
const draft = ref<Record<string, string>>({})
const plan = ref<MetadataPlanItem | null>(null)
const loading = ref(false)
const planning = ref(false)
const saving = ref(false)

/** 数组字段（tags）在草稿里用「、」连接，提交前拆回去 */
function toText(key: FieldKey, v: unknown): string {
  if (Array.isArray(v)) return v.join('、')
  return v === undefined || v === null ? '' : String(v)
}

function load(): void {
  loading.value = true
  api
    .bookMetadata(props.item.book_id)
    .then((m) => {
      meta.value = m
      const d: Record<string, string> = {}
      for (const f of FIELDS) d[f.key] = toText(f.key, m.fields[f.key])
      draft.value = d
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

/** Esc 关闭：挂在 window 上（抽屉本体不一定拿得到焦点） */
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

/** 已知的候选字段值（`changes` 的键是 OPF 口径，与 FIELDS 同名） */
const candidates = computed(() => {
  const ch = plan.value?.changes ?? {}
  return Object.keys(ch).filter((k) => FIELDS.some((f) => f.key === k))
})

function useCandidate(key: string): void {
  const to = plan.value?.changes?.[key]?.to
  draft.value[key] = toText(key as FieldKey, to)
}

/** 候选值预览文案（模板里不能直接对可能为空的 plan 取双层属性） */
function candText(key: string): string {
  return toText(key as FieldKey, plan.value?.changes?.[key]?.to)
}

function useAllCandidates(): void {
  for (const k of candidates.value) useCandidate(k)
  ui.toast(`已采用 ${candidates.value.length} 个字段候选，记得点「应用并重建」`)
}

async function fetchCandidates(): Promise<void> {
  planning.value = true
  try {
    const p = await api.metadataPlan([props.item.name])
    plan.value = p.items?.[0] ?? null
    if (!plan.value || plan.value.skipped || plan.value.error) {
      ui.toast(plan.value?.skipped || plan.value?.error || '没有找到候选')
    } else if (!candidates.value.length) {
      ui.toast('候选与当前值一致，没有可采用的字段')
    }
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '抓取候选失败')
  } finally {
    planning.value = false
  }
}

const changedKeys = computed(() => FIELDS.map((f) => f.key).filter((k) => isDirty(k)))

function isDirty(key: FieldKey): boolean {
  const cur = meta.value ? toText(key, meta.value.fields[key]) : ''
  return (draft.value[key] ?? '') !== cur
}

async function applyAndRebuild(): Promise<void> {
  saving.value = true
  try {
    const fields: Partial<BookMetadataFields> = {}
    for (const k of changedKeys.value) {
      if (k === 'tags') {
        fields.tags = (draft.value[k] ?? '')
          .split(/[、,，;；|]/)
          .map((s) => s.trim())
          .filter(Boolean)
      } else {
        ;(fields as Record<string, string>)[k] = draft.value[k] ?? ''
      }
    }
    if (Object.keys(fields).length) await api.setBookMetadata(props.item.book_id, fields)
    // 重建副本 = 把「刚写进去的生效值」真正落到外部阅读器能看到的那份文件上
    await api.scrapeResolve(props.item.book_id, 'rebuild')
    ui.toast(
      Object.keys(fields).length
        ? `已写入 ${Object.keys(fields).length} 个字段并重建副本，外部阅读器可以读到了`
        : '已按当前元数据重建副本',
    )
    emit('applied')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '应用失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-40 flex justify-end">
    <div class="flex-1 bg-black/25" @click="emit('close')" />

    <aside
      class="flex h-full w-full flex-col border-l border-border bg-card shadow-2xl sm:w-[min(32.5rem,94vw)]"
      style="animation: slideIn 180ms ease-out"
      role="dialog"
      aria-label="整理元数据"
      @keydown.esc="emit('close')"
    >
      <header class="shrink-0 border-b border-border px-4 py-3">
        <div class="flex items-center gap-2">
          <h3 class="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-foreground" :title="item.title">
            {{ item.title }}
          </h3>
          <Button size="sm" variant="ghost" @click="emit('close')">关闭</Button>
        </div>
        <div class="mt-1 text-[11px] text-muted-foreground">
          改的是<strong>副本</strong>，原文件保持原样
        </div>
      </header>

      <div class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <div v-if="loading" class="py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

        <template v-else>
          <div class="mb-3 rounded-md border border-border bg-muted px-3 py-2">
            <div class="flex items-start gap-1.5 text-[11px] text-muted-foreground">
              <Icon name="book" class="mt-0.5 h-3 w-3 shrink-0" />
              <span class="min-w-0 flex-1 break-all">{{ item.source_path }}</span>
            </div>
            <div class="mt-1 flex items-start gap-1.5 text-[11px] text-muted-foreground">
              <Icon name="layers" class="mt-0.5 h-3 w-3 shrink-0" />
              <span class="min-w-0 flex-1 break-all">{{ item.copy_path || '（尚未产出副本）' }}</span>
            </div>
          </div>

          <div class="mb-3 flex flex-wrap items-center gap-2">
            <Button size="sm" :disabled="planning" @click="fetchCandidates">
              {{ planning ? '抓取中…' : '抓取在线候选' }}
            </Button>
            <Button v-if="candidates.length" size="sm" variant="ghost" @click="useAllCandidates">
              采用全部 {{ candidates.length }} 项
            </Button>
            <span v-if="plan" class="text-[11px] text-muted-foreground">
              最佳匹配分 {{ Math.round((plan.best_score ?? 0) * 100) }}%
            </span>
          </div>

          <div class="space-y-2.5">
            <div v-for="f in FIELDS" :key="f.key" class="relative pl-2">
              <!-- 改动过的字段左侧竖条：一眼看出「这次动了什么」 -->
              <span
                v-if="isDirty(f.key)"
                class="absolute top-4 left-0 h-[calc(100%-1rem)] w-[2px] rounded-full bg-primary"
                aria-hidden="true"
              />
              <div class="mb-1 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                {{ f.label }}
                <Badge v-if="isDirty(f.key)" tone="accent">已改</Badge>
                <button
                  v-if="plan?.changes?.[f.key]"
                  type="button"
                  class="ml-auto cursor-pointer rounded px-1.5 py-0.5 text-[10.5px] text-primary hover:bg-primary/10"
                  :title="candText(f.key)"
                  @click="useCandidate(f.key)"
                >
                  采用候选
                </button>
              </div>
              <textarea
                v-if="f.multiline"
                v-model="draft[f.key]"
                rows="3"
                class="w-full resize-y rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-primary"
              />
              <input
                v-else
                v-model="draft[f.key]"
                type="text"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>
          </div>
        </template>
      </div>

      <footer class="shrink-0 border-t border-border px-4 py-3">
        <div class="mb-2 text-[11px] text-muted-foreground">
          将重建的副本：<span class="break-all text-foreground">{{ item.copy_path || '（首次生成）' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <span v-if="changedKeys.length" class="text-[11.5px] text-muted-foreground">
            已改 {{ changedKeys.length }} 个字段
          </span>
          <Button
            class="ml-auto"
            variant="primary"
            size="sm"
            :disabled="saving || loading"
            @click="applyAndRebuild"
          >
            {{ saving ? '处理中…' : '应用并重建' }}
          </Button>
        </div>
      </footer>
    </aside>
  </div>
</template>

<style scoped>
@keyframes slideIn {
  from {
    transform: translateX(24px);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}
</style>
