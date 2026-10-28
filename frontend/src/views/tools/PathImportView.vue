<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import LibraryScopeSwitch from '@/components/tools/LibraryScopeSwitch.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, type PathImportMeta, type PathImportPreview, type PathImportResult } from '@/lib/api'
import { FIELD_LABELS } from '@/lib/metadataFields'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 文件名提取（第 165 期）：按正则从文件名 / 路径批量提取元数据。
 *
 * 三段式，缺一不可：
 *   1. **规则**：匹配范围 + 一条正则，命名分组写元数据字段名（`(?P<author>…)`）；
 *   2. **预览**：只读 —— 匹配多少本、每本哪些字段会变（服务端算，前端不算第二遍）；
 *   3. **应用**：服务端**重新算**一遍再写（预览条目只用来给人看，不参与写入）。
 *
 * 写的是**服务端覆盖**（`meta_override`），与详情页「编辑元数据」同一条路径：
 * 书文件一字节不动，改错了可逐本「恢复为在线值」。
 *
 * ⚠️ 可写字段 / 匹配范围由后端下发（`path-import/meta`），前端不静态抄一份 ——
 * 抄了之后加字段就会两边不一致。
 */
const ui = useUiStore()
const library = useLibraryStore()

const meta = ref<PathImportMeta | null>(null)
const pattern = ref('')
const target = ref('stem')
/** 空串 = 全部书库（与工具页「范围」同一个语义） */
const libScope = ref('')
const preview = ref<PathImportPreview | null>(null)
const result = ref<PathImportResult | null>(null)
const busy = ref('')
const error = ref('')

const targetLabel = computed(() => {
  const t = meta.value?.targets.find((x) => x.value === target.value)
  return t?.label || target.value
})

function fieldLabel(f: string): string {
  return (FIELD_LABELS as Record<string, string>)[f] || f
}

function fmtValue(v: unknown): string {
  if (Array.isArray(v)) return v.join('、')
  return String(v ?? '') || '（空）'
}

/** 示例：点一下直接填进输入框（不用手抄正则） */
const EXAMPLES = [
  {
    label: '方括号作者 + 书名 + 年份',
    pattern: '^\\[(?P<author>[^\\]]+)\\]\\s*(?P<title>.+?)\\s*\\((?P<date>\\d{4})\\)$',
  },
  {
    label: '系列目录 + 卷号',
    pattern: '^(?P<series>.+?)/第(?P<series_index>\\d+)卷',
  },
]

function useExample(p: string): void {
  pattern.value = p
  preview.value = null
  result.value = null
  error.value = ''
}

async function loadMeta(): Promise<void> {
  void library.loadLibraries()
  try {
    meta.value = await api.pathImportMeta()
    if (!meta.value.targets.some((t) => t.value === target.value)) {
      target.value = meta.value.targets[0]?.value || 'stem'
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读不到可写字段'
  }
}

onMounted(loadMeta)

async function runPreview(): Promise<void> {
  if (!pattern.value.trim() || busy.value) return
  busy.value = 'preview'
  error.value = ''
  result.value = null
  try {
    preview.value = await api.pathImportPreview({
      pattern: pattern.value,
      target: target.value,
      library_id: libScope.value || undefined,
    })
  } catch (e) {
    preview.value = null
    error.value = e instanceof Error ? e.message : '预览失败'
  } finally {
    busy.value = ''
  }
}

async function runApply(): Promise<void> {
  if (!preview.value?.changed || busy.value) return
  busy.value = 'apply'
  error.value = ''
  try {
    result.value = await api.pathImportApply({
      pattern: pattern.value,
      target: target.value,
      library_id: libScope.value || undefined,
    })
    const r = result.value
    ui.toast(r.errors.length
      ? `已写入 ${r.count} 本，${r.errors.length} 本失败`
      : `已写入 ${r.count} 本`)
    // 写完再算一次：预览里的「会变」应归零（也让用户看见实际结果）
    preview.value = await api.pathImportPreview({
      pattern: pattern.value,
      target: target.value,
      library_id: libScope.value || undefined,
    })
  } catch (e) {
    error.value = e instanceof Error ? e.message : '应用失败'
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">文件名提取</h2>
      <span class="text-[11.5px] text-muted-foreground">
        按正则从文件名 / 路径批量提取元数据（先预览、再应用；只写服务端，不动书文件）
      </span>
    </div>

    <Card>
      <div class="flex flex-wrap items-center gap-3">
        <LibraryScopeSwitch v-model="libScope" />
        <label class="flex items-center gap-1.5 text-[12px] text-muted-foreground">
          匹配
          <select
            v-model="target"
            aria-label="匹配范围"
            class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
          >
            <option v-for="t in meta?.targets ?? []" :key="t.value" :value="t.value">{{ t.label }}</option>
          </select>
        </label>
      </div>

      <label class="mt-3 flex flex-col gap-1">
        <span class="text-[11.5px] text-muted-foreground">
          正则（命名分组 = 字段名，例如 <code class="font-mono">(?P&lt;author&gt;…)</code>）
        </span>
        <textarea
          v-model="pattern"
          rows="2"
          spellcheck="false"
          aria-label="提取正则"
          placeholder="^\\((?P<author>[^)]+)\\)\\s*(?P<title>.+)$"
          class="w-full rounded-md border border-border bg-card p-2 font-mono text-[12px] text-foreground outline-none focus:border-ring"
          @keydown.ctrl.enter.prevent="runPreview"
        />
      </label>

      <div class="mt-2 flex flex-wrap items-center gap-2">
        <span class="text-[11.5px] text-muted-foreground">示例：</span>
        <button
          v-for="ex in EXAMPLES"
          :key="ex.label"
          type="button"
          class="cursor-pointer rounded-full bg-muted px-2 py-0.5 text-[11.5px] text-muted-foreground hover:text-foreground"
          @click="useExample(ex.pattern)"
        >
          {{ ex.label }}
        </button>
        <Button size="sm" class="ml-auto" :disabled="!!busy || !pattern.trim()" @click="runPreview">
          {{ busy === 'preview' ? '匹配中…' : '预览' }}
        </Button>
      </div>
      <p v-if="meta" class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        可写字段：{{ meta.fields.join(' / ') }}。空匹配值的字段<strong>不会被清空</strong>；
        命名分组拼错会直接报错，不会静默忽略。
      </p>
      <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <Card v-if="preview">
      <div class="flex flex-wrap items-center gap-2">
        <h3 class="text-[13px] font-semibold text-foreground">预览</h3>
        <Badge tone="accent">{{ targetLabel }}</Badge>
        <span class="text-[12px] text-muted-foreground">
          共 {{ preview.total }} 本 · 匹配 {{ preview.matched }} 本 · 未匹配 {{ preview.unmatched }} 本
          · 会改写 {{ preview.changed }} 本
        </span>
        <Button
          size="sm"
          variant="primary"
          class="ml-auto"
          :disabled="!!busy || !preview.changed"
          @click="runApply"
        >
          {{ busy === 'apply' ? '写入中…' : `应用到 ${preview.changed} 本` }}
        </Button>
      </div>
      <div class="mt-1.5 flex flex-wrap gap-1">
        <Badge v-for="f in preview.fields" :key="f" tone="neutral">{{ fieldLabel(f) }}</Badge>
      </div>

      <div v-if="result" class="mt-2 rounded-md border border-border p-2 text-[12px]">
        已写入 <b class="text-foreground">{{ result.count }}</b> 本
        <span v-if="result.errors.length" class="text-destructive">
          ，{{ result.errors.length }} 本失败：{{ result.errors[0].name }}（{{ result.errors[0].error }}）
        </span>
        <span v-else class="text-muted-foreground">，没有失败。</span>
      </div>

      <div class="mt-2 overflow-x-auto">
        <table class="w-full min-w-[36rem] border-collapse text-left">
          <thead>
            <tr class="border-b border-border text-[11.5px] text-muted-foreground">
              <th class="px-2 py-1.5 font-semibold">书名 / 文件名</th>
              <th class="px-2 py-1.5 font-semibold">提取值</th>
              <th class="px-2 py-1.5 font-semibold">变化</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in preview.items"
              :key="it.book_id"
              class="border-b border-border/60 text-[12px] last:border-b-0"
            >
              <td class="max-w-[15rem] truncate px-2 py-1.5 text-foreground" :title="it.name">
                {{ it.title }}
                <span class="ml-1 text-[11px] text-muted-foreground">{{ it.name }}</span>
              </td>
              <td class="px-2 py-1.5 text-muted-foreground">
                <span v-for="(v, f) in it.values" :key="f" class="mr-2">
                  {{ fieldLabel(String(f)) }}：<span class="text-foreground">{{ fmtValue(v) }}</span>
                </span>
              </td>
              <td class="px-2 py-1.5">
                <span v-if="!it.changes.length" class="text-[11.5px] text-muted-foreground">无变化</span>
                <span v-else class="text-[11.5px] text-amber-600 dark:text-amber-400">
                  {{ it.changes.map((c) => fieldLabel(c.field)).join('、') }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="preview.truncated" class="mt-1.5 text-[11.5px] text-muted-foreground">
        只显示前 {{ preview.limit }} 条；上面的计数覆盖全部匹配。
      </p>
      <p class="mt-1.5 text-[11.5px] text-muted-foreground">
        写入的是服务端元数据覆盖（与「编辑元数据」同一条路径）：书文件不动，改错了可逐本恢复。
      </p>
    </Card>

    <EmptyState
      v-else-if="!pattern.trim()"
      icon="file"
      title="先写一条正则"
      desc="命名分组用元数据字段名（如 (?P<author>…)），点「预览」看匹配结果，确认后再应用。"
    />
  </div>
</template>
