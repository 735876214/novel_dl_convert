<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api } from '@/lib/api'
import {
  ruleText,
  schemaMaps,
  type RuleSchema,
  type ScopeRule,
  type SmartScope,
} from '@/lib/smartScope'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'
import { useDndSort } from '@/composables/useDndSort'

/**
 * 自定义智能书架管理页：规则的增删改 + 实时预览。
 *
 * 第 218 期起**求值在服务端**（`core/bookrules.py`）：字段 / 操作清单来自
 * `GET /api/book-rules`，预览走 `POST /api/smart-scopes/preview`，列表命中数由
 * `GET /api/smart-scopes` 一并返回。前端不再加载全量书目自己算规则。
 */
const router = useRouter()
const library = useLibraryStore()
const ui = useUiStore()

const scopes = ref<SmartScope[]>([])
const loading = ref(true)
/** 加载失败信息：失败不能退化成「还没有自定义书架」（否则「拉不到」被误读成「一条都没有」）。 */
const error = ref('')

/** 规则字段 / 操作清单（服务端单一真值源） */
const schema = ref<RuleSchema | null>(null)
const schemaError = ref('')
const maps = computed(() => schemaMaps(schema.value))

async function loadSchema(): Promise<void> {
  schemaError.value = ''
  try {
    schema.value = await api.ruleSchema()
  } catch (e) {
    schema.value = null
    schemaError.value = e instanceof Error ? e.message : '加载字段清单失败'
  }
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    scopes.value = (await api.smartScopes(library.currentLibraryId)).items
    library.scopes.splice(0, library.scopes.length, ...scopes.value)
  } catch (e) {
    scopes.value = []
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  await Promise.all([loadSchema(), load()])
})

/** 手动排序（第 154 期）：拖拽与上下移共用一个提交口。 */
async function move(from: number, to: number): Promise<void> {
  if (to < 0 || to >= scopes.value.length || from === to) return
  const ids = scopes.value.map((s) => s.id)
  const [moved] = ids.splice(from, 1)
  ids.splice(to, 0, moved)
  const byId = new Map(scopes.value.map((s) => [s.id, s]))
  scopes.value = ids.map((id) => byId.get(id)).filter((s): s is SmartScope => !!s)
  try {
    scopes.value = (await api.reorderSmartScopes(ids, library.currentLibraryId)).items
    library.scopes.splice(0, library.scopes.length, ...scopes.value)
  } catch (e) {
    await load()
    ui.toast(e instanceof Error ? e.message : '排序失败')
  }
}

const dnd = useDndSort({ onCommit: (from, to) => void move(from, to) })

// ---------- 编辑表单 ----------
const editing = ref<number | null>(null) // null = 不在编辑；-1 = 新建
const fName = ref('')
const fMatch = ref<'all' | 'any'>('all')
const fRules = ref<ScopeRule[]>([])
const saving = ref(false)

const isEditing = computed(() => editing.value !== null)

function emptyRule(): ScopeRule {
  const f = schema.value?.fields.find((x) => x.key === 'author') || schema.value?.fields[0]
  return { field: f?.key || 'author', op: f?.ops[0] || 'contains', value: '' }
}

function startCreate(): void {
  editing.value = -1
  fName.value = ''
  fMatch.value = 'all'
  fRules.value = [emptyRule()]
  schedulePreview()
}

function startEdit(s: SmartScope): void {
  editing.value = s.id
  fName.value = s.name
  fMatch.value = s.match
  fRules.value = (s.rules || []).map((r) => ({ ...r }))
  schedulePreview()
}

function cancel(): void {
  editing.value = null
  clearPreviewTimer()
  previewCount.value = null
  previewError.value = ''
}

/** 字段切换时，若当前操作不被新字段支持则落到该字段的第一个合法操作 */
function onFieldChange(r: ScopeRule): void {
  const ops = maps.value.fieldOps[r.field] || []
  if (!ops.includes(r.op)) r.op = ops[0] || 'equals'
}

/** 这个操作要不要填值（「为空 / 不为空」不要） */
function opNeedsValue(r: ScopeRule): boolean {
  return maps.value.opNeedsValue[r.op] ?? true
}

function ruleValid(r: ScopeRule): boolean {
  return !opNeedsValue(r) || Boolean(String(r.value ?? '').trim())
}

const canSave = computed(
  () => Boolean(schema.value) && fName.value.trim() && fRules.value.length > 0
    && fRules.value.every(ruleValid),
)

// ---------- 实时预览（服务端求值，防抖）----------
const previewCount = ref<number | null>(null)
const previewError = ref('')
const previewLoading = ref(false)
let previewTimer: ReturnType<typeof setTimeout> | null = null
let previewSeq = 0

function clearPreviewTimer(): void {
  if (previewTimer !== null) {
    clearTimeout(previewTimer)
    previewTimer = null
  }
}

async function refreshPreview(): Promise<void> {
  const seq = ++previewSeq
  if (!isEditing.value || !canSave.value) {
    previewCount.value = null
    previewError.value = ''
    return
  }
  previewLoading.value = true
  try {
    const res = await api.previewSmartScope({
      rules: fRules.value.map((r) => ({
        field: r.field, op: r.op, value: String(r.value ?? '').trim(),
      })),
      match: fMatch.value,
      library_id: library.currentLibraryId,
    })
    if (seq === previewSeq) {
      previewCount.value = res.count
      previewError.value = ''
    }
  } catch (e) {
    if (seq === previewSeq) {
      previewCount.value = null
      previewError.value = e instanceof Error ? e.message : '预览失败'
    }
  } finally {
    if (seq === previewSeq) previewLoading.value = false
  }
}

function schedulePreview(): void {
  clearPreviewTimer()
  previewTimer = setTimeout(() => void refreshPreview(), 250)
}

watch([fName, fRules, fMatch, () => library.currentLibraryId], schedulePreview, { deep: true })
onBeforeUnmount(clearPreviewTimer)

async function save(): Promise<void> {
  if (!canSave.value || saving.value) return
  saving.value = true
  const payload = {
    name: fName.value.trim(),
    rules: fRules.value.map((r) => ({ field: r.field, op: r.op, value: String(r.value).trim() })),
    match: fMatch.value,
  }
  try {
    const id = editing.value
    if (id === -1) await api.createSmartScope(payload)
    else if (id !== null) await api.updateSmartScope(id, payload)
    ui.toast('已保存智能书架')
    editing.value = null
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(s: SmartScope): Promise<void> {
  if (!window.confirm(`删除智能书架「${s.name}」？只删规则，不动书。`)) return
  try {
    await api.deleteSmartScope(s.id)
    await load()
    ui.toast('已删除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

function openOnShelf(s: SmartScope): void {
  library.openSmart(s.name, `scope:${s.id}`)
  router.push('/shelf')
}

const fieldOptions = computed(() => schema.value?.fields || [])
function opOptions(field: string): string[] {
  return maps.value.fieldOps[field] || []
}
function opLabel(op: string): string {
  return maps.value.opLabels[op] ?? op
}
function fieldValues(field: string): { value: string; label: string }[] {
  return maps.value.fieldValues[field] || []
}
</script>

<template>
  <div>
    <PageHead title="自定义智能书架" desc="把常用的筛选组合存成规则书架，出现在侧栏「智能书架」里" />

    <!-- 编辑 / 新建表单 -->
    <Card v-if="isEditing" class="mb-4">
      <h3 class="mb-3 text-[13px] font-semibold text-foreground">
        {{ editing === -1 ? '新建智能书架' : '编辑智能书架' }}
      </h3>

      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <span>名称</span>
          <input
            v-model="fName"
            type="text"
            aria-label="智能书架名称"
            placeholder="如：近年科幻"
            class="h-8 w-48 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
        </label>
        <label class="flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <span>匹配</span>
          <select v-model="fMatch" aria-label="匹配方式" class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring">
            <option value="all">满足全部规则（且）</option>
            <option value="any">满足任一规则（或）</option>
          </select>
        </label>
        <span class="ml-auto text-[12px] text-muted-foreground">
          <template v-if="previewLoading">预览中…</template>
          <template v-else-if="previewError">
            <span class="text-destructive">预览失败：{{ previewError }}</span>
          </template>
          <template v-else-if="previewCount !== null">
            命中 <b class="text-foreground tabular-nums">{{ previewCount }}</b> 本（服务端实时预览）
          </template>
          <template v-else>填完整规则后显示命中数</template>
        </span>
      </div>

      <p v-if="schemaError" class="mt-2 flex items-center gap-2 text-[12px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>规则字段清单加载失败：{{ schemaError }}</span>
        <button type="button" class="cursor-pointer underline" @click="loadSchema">重试</button>
      </p>

      <div class="mt-3 flex flex-col gap-2">
        <div v-for="(r, i) in fRules" :key="i" class="flex flex-wrap items-center gap-2">
          <select v-model="r.field" aria-label="规则字段" class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring" @change="onFieldChange(r)">
            <option v-for="f in fieldOptions" :key="f.key" :value="f.key">{{ f.label }}</option>
          </select>
          <select v-model="r.op" aria-label="规则操作符" class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring">
            <option v-for="o in opOptions(r.field)" :key="o" :value="o">{{ opLabel(o) }}</option>
          </select>
          <template v-if="opNeedsValue(r)">
            <select
              v-if="fieldValues(r.field).length"
              v-model="r.value"
              aria-label="规则值"
              class="h-8 w-52 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            >
              <option value="">选择…</option>
              <option v-for="v in fieldValues(r.field)" :key="v.value" :value="v.value">{{ v.label }}</option>
            </select>
            <input
              v-else
              v-model="r.value"
              type="text"
              aria-label="规则值"
              :placeholder="r.field === 'added' ? '天数（如 30）' : '值'"
              class="h-8 w-52 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
            >
          </template>
          <span v-else class="text-[11.5px] text-muted-foreground">（无需填值）</span>
          <button
            type="button"
            class="cursor-pointer text-[12px] text-muted-foreground hover:text-destructive"
            :disabled="fRules.length <= 1"
            @click="fRules.splice(i, 1)"
          >
            移除
          </button>
        </div>
      </div>
      <button
        type="button"
        class="mt-2 cursor-pointer text-[12px] text-primary hover:underline"
        @click="fRules.push(emptyRule())"
      >
        + 加一条规则
      </button>

      <div class="mt-4 flex items-center gap-2 border-t border-border pt-3">
        <button
          type="button"
          class="cursor-pointer rounded-md bg-primary px-3.5 py-1.5 text-[12.5px] font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canSave || saving"
          @click="save"
        >
          保存
        </button>
        <button type="button" class="cursor-pointer rounded-md px-3 py-1.5 text-[12.5px] text-muted-foreground hover:text-foreground" @click="cancel">
          取消
        </button>
        <span v-if="!canSave" class="text-[11.5px] text-muted-foreground">
          {{ schema ? '名称必填；需要值的规则要填值。' : '字段清单尚未加载。' }}
        </span>
      </div>
    </Card>

    <!-- 已有书架列表 -->
    <Card padding="sm">
      <div class="flex items-center justify-between">
        <h3 class="text-[13px] font-semibold text-foreground">已有书架（{{ scopes.length }}）</h3>
        <button
          v-if="!isEditing"
          type="button"
          class="cursor-pointer rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!schema"
          @click="startCreate"
        >
          新建
        </button>
      </div>

      <p role="status" aria-live="polite" v-if="loading" class="py-6 text-center text-[12.5px] text-muted-foreground">加载中…</p>
      <div v-else-if="error" class="flex flex-wrap items-center gap-2 py-4 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>加载智能书架失败：{{ error }}</span>
        <button
          type="button"
          class="ml-auto cursor-pointer rounded-md border border-border px-2.5 py-1 text-[12px] text-foreground transition-colors hover:bg-muted"
          @click="load"
        >
          重试
        </button>
      </div>
      <p v-else-if="!scopes.length" class="py-8 text-center text-[12.5px] text-muted-foreground">
        还没有自定义书架。点「新建」，把常用筛选（比如「作者包含某某 且 评分至少 4」）存成规则。
      </p>

      <div
        v-for="(s, index) in scopes"
        :key="s.id"
        :data-scope-row="s.id"
        :draggable="true"
        class="flex items-center gap-3 border-b border-border/60 py-2.5 last:border-b-0"
        :class="dnd.dragOverIndex.value === index ? 'bg-muted/60' : ''"
        @dragstart="dnd.onDragStart(index, $event)"
        @dragover="dnd.onDragOver(index, $event)"
        @drop.prevent="dnd.onDrop(index)"
        @dragend="dnd.onDragEnd"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] font-medium text-foreground">{{ s.name }}</div>
          <div class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
            {{ s.match === 'any' ? '任一' : '全部' }} · {{ s.rules.map((r) => ruleText(r, schema)).join('；') }}
          </div>
        </div>
        <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">
          {{ s.count ?? 0 }} 本
        </span>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40" title="上移" aria-label="上移" :disabled="index === 0" @click="move(index, index - 1)">↑</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40" title="下移" aria-label="下移" :disabled="index === scopes.length - 1" @click="move(index, index + 1)">↓</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground" @click="openOnShelf(s)">打开</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground" @click="startEdit(s)">编辑</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-destructive" @click="remove(s)">删除</button>
      </div>
    </Card>
  </div>
</template>
