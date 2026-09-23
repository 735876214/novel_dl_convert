<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type BookCard } from '@/lib/api'
import {
  evaluateScope,
  FIELD_LABELS,
  FIELD_OPS,
  OP_LABELS,
  ruleText,
  type ScopeField,
  type ScopeOp,
  type ScopeRule,
  type SmartScope,
} from '@/lib/smartScope'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 自定义智能书架管理页：规则的增删改。
 * 规则存后端（smart_scopes 表）、求值在前端（lib/smartScope.ts），
 * 编辑时用当前书单做**实时预览计数**——用户不用保存后才知道规则框住了几本书。
 */
const router = useRouter()
const library = useLibraryStore()
const ui = useUiStore()

const scopes = ref<SmartScope[]>([])
const loading = ref(true)
/** 加载失败信息：失败不能退化成「还没有自定义书架」（否则「拉不到」被误读成「一条都没有」）。 */
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    scopes.value = (await api.smartScopes()).items
    library.scopes.splice(0, library.scopes.length, ...scopes.value)
  } catch (e) {
    scopes.value = []
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(async () => {
  await library.loadBooks()
  await load()
})

// ---------- 编辑表单 ----------
const editing = ref<number | null>(null) // null = 不在编辑；-1 = 新建
const fName = ref('')
const fMatch = ref<'all' | 'any'>('all')
const fRules = ref<ScopeRule[]>([])
const saving = ref(false)

const isEditing = computed(() => editing.value !== null)

function emptyRule(): ScopeRule {
  return { field: 'author', op: 'contains', value: '' }
}

function startCreate(): void {
  editing.value = -1
  fName.value = ''
  fMatch.value = 'all'
  fRules.value = [emptyRule()]
}

function startEdit(s: SmartScope): void {
  editing.value = s.id
  fName.value = s.name
  fMatch.value = s.match
  fRules.value = (s.rules || []).map((r) => ({ ...r }))
}

function cancel(): void {
  editing.value = null
}

/** 字段切换时，若当前操作不被新字段支持则落到该字段的第一个合法操作 */
function onFieldChange(r: ScopeRule): void {
  const ops = FIELD_OPS[r.field]
  if (!ops.includes(r.op)) r.op = ops[0]
}

function ruleValid(r: ScopeRule): boolean {
  return Boolean(String(r.value ?? '').trim())
}

const canSave = computed(
  () => fName.value.trim() && fRules.value.length > 0 && fRules.value.every(ruleValid),
)

/** 实时预览：当前书单里命中规则的数量 */
const previewCount = computed(() =>
  evaluateScope(library.books as BookCard[], fRules.value, fMatch.value).length,
)

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

const FIELD_OPTIONS = Object.keys(FIELD_LABELS) as ScopeField[]
function opOptions(field: ScopeField): ScopeOp[] {
  return FIELD_OPS[field]
}
function opLabel(op: ScopeOp): string {
  return OP_LABELS[op] ?? op
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
          命中 <b class="text-foreground tabular-nums">{{ previewCount }}</b> 本（实时预览）
        </span>
      </div>

      <div class="mt-3 flex flex-col gap-2">
        <div v-for="(r, i) in fRules" :key="i" class="flex flex-wrap items-center gap-2">
          <select v-model="r.field" aria-label="规则字段" class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring" @change="onFieldChange(r)">
            <option v-for="f in FIELD_OPTIONS" :key="f" :value="f">{{ FIELD_LABELS[f] }}</option>
          </select>
          <select v-model="r.op" aria-label="规则操作符" class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring">
            <option v-for="o in opOptions(r.field)" :key="o" :value="o">{{ opLabel(o) }}</option>
          </select>
          <input
            v-model="r.value"
            type="text"
            aria-label="规则值"
            placeholder="值"
            class="h-8 w-52 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
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
        <span v-if="!canSave" class="text-[11.5px] text-muted-foreground">名称与每条规则的值都必填。</span>
      </div>
    </Card>

    <!-- 已有书架列表 -->
    <Card padding="sm">
      <div class="flex items-center justify-between">
        <h3 class="text-[13px] font-semibold text-foreground">已有书架（{{ scopes.length }}）</h3>
        <button
          v-if="!isEditing"
          type="button"
          class="cursor-pointer rounded-md bg-primary px-3 py-1.5 text-[12.5px] font-medium text-primary-foreground"
          @click="startCreate"
        >
          新建
        </button>
      </div>

      <p v-if="loading" class="py-6 text-center text-[12.5px] text-muted-foreground">加载中…</p>
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
        v-for="s in scopes"
        :key="s.id"
        class="flex items-center gap-3 border-b border-border/60 py-2.5 last:border-b-0"
      >
        <div class="min-w-0 flex-1">
          <div class="truncate text-[13px] font-medium text-foreground">{{ s.name }}</div>
          <div class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
            {{ s.match === 'any' ? '任一' : '全部' }} · {{ s.rules.map(ruleText).join('；') }}
          </div>
        </div>
        <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">
          {{ evaluateScope(library.books as BookCard[], s.rules, s.match).length }} 本
        </span>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground" @click="openOnShelf(s)">打开</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-foreground" @click="startEdit(s)">编辑</button>
        <button type="button" class="shrink-0 cursor-pointer text-[12px] text-muted-foreground hover:text-destructive" @click="remove(s)">删除</button>
      </div>
    </Card>
  </div>
</template>
