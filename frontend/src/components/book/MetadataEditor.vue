<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type BookMetadata, type BookMetadataFields, type BookMetadataWriteFields } from '@/lib/api'
import { CATALOG_FIELDS, DB_ONLY_FIELDS, FIELD_LABELS, IDENTITY_FIELDS } from '@/lib/metadataFields'
import { useUiStore } from '@/stores/ui'

/**
 * 单书元数据编辑（详情页第 5 个标签）。
 *
 * 元数据分层原则（第 8 期）：生效值 = 用户覆盖(override) > 在线抓取(online) > 文件原值(opf)。
 *  - 编辑保存：与生效原值不同的字段记入**服务端覆盖**，再抓取不冲掉；
 *  - 已覆盖的字段显示「已本地修改」徽标 + 「恢复在线」按钮（撤销覆盖，回落在线值）；
 *  - **「清空」**（第 22 期）：把字段置为「真的没有值」（提交 `null`，后端写无值标记）——
 *    与「恢复在线」相反：恢复是撤掉改动、回落到抓取值 / 文件原值，清空则是显式无值、
 *    之后抓取也不会把它填回来。两种动作并存，别再让「删空输入框」承担清空语义
 *    （空串仍是「撤销覆盖」，EPUB 上的老行为不变）。
 *
 * **「锁定」**（第 35 期）与前三种都不同，它是**抓取开关**而不是取值动作：
 *  - 锁上 ⇒ 在线抓取永不改写该字段，**即使该字段的策略写着「总是覆盖」**；界面标「已锁定」；
 *  - 但**不挡手动编辑** —— 用户当下改一手的意志走在最顶层，不该被一个更早的标记拦下；
 *  - 与「已本地修改」**正交**：可以没改过但锁上（抓取别动），也可以改过但没锁（抓取之后可接管）。
 *  封面用独立键 `cover`：封面图不在 `fields` 里，锁状态从 `meta.locked` 那份扁平清单读。
 *
 * ⚠️ 第 18 期起保存**不改写书文件**（只有服务端 DB 变），所以界面文案说的是
 * 「存到应用数据库、所有界面一致」，而不是「写进文件」——别再写成写文件，
 * 否则用户会以为把书改脏了。第 22 期起**所有格式都可编辑**（原先限 EPUB 的
 * 理由是「兜底原值来自 OPF」，改动只落库后这条前提已不成立）。
 */
const props = defineProps<{ bookId: string }>()
const emit = defineEmits<{ saved: [] }>()

/** 封面锁的字段键（后端 `db.LOCK_COVER`）——不在 BookMetadataFields 里 */
const COVER = 'cover'

const ui = useUiStore()
const meta = ref<BookMetadata | null>(null)
const loading = ref(true)
const saving = ref(false)
const restoring = ref(false)
const clearing = ref(false)
/** 正在切换锁的字段（避免连点；一次只切一个） */
const locking = ref('')
const form = ref<BookMetadataFields | null>(null)
const changed = ref<string[]>([])
const tagText = ref('')
/** 演播者草稿（第 53 期，与题材同构：用「、」或逗号分隔，保存时自动去重保序） */
const narratorText = ref('')

/**
 * 界面的两段（顺序与分组对齐上游编辑器）：
 * **IDENTITY**（这本书是什么）与 **CATALOG**（它在外部数据库里的编号）。
 *
 * 字段名与中文名统一从 `lib/metadataFields.ts` 取 —— 那份清单原先在这里、
 * 抓取抽屉、设置页、Book Dock 各抄了一遍，且已经抄出过事故（见该文件头）。
 */
const GROUPS: Array<{ title: string; hint: string; fields: (keyof BookMetadataFields)[] }> = [
  {
    title: '标识',
    hint: '书名 / 作者 / 系列等 —— 决定它在书架上怎么显示',
    fields: IDENTITY_FIELDS,
  },
  {
    title: '目录号',
    hint: 'ISBN 与各来源的编号。这些字段只存应用数据库，'
      + '本项目的元数据抓取会填它们（填不到就留空，不猜）',
    fields: CATALOG_FIELDS,
  },
]

async function load(): Promise<void> {
  loading.value = true
  changed.value = []
  try {
    meta.value = await api.bookMetadata(props.bookId)
    form.value = { ...(meta.value?.fields as BookMetadataFields) }
    tagText.value = (form.value.tags || []).join('、')
    narratorText.value = (form.value.narrators || []).join('、')
    resetCustom()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '元数据加载失败')
    meta.value = null
  }
  loading.value = false
}

onMounted(load)
watch(() => props.bookId, load)

const editable = computed(() => meta.value?.editable === true)

/** 是否有任意字段被用户本地覆盖（决定「恢复全部为在线」是否可用） */
const hasOverrides = computed(() =>
  !!meta.value && Object.values(meta.value.meta).some((m) => m.overridden),
)

/** 是否有未保存的改动（与加载时的生效值比对；**含自定义字段**——它们是同一张表单） */
const dirty = computed(() => {
  if (!meta.value || !form.value) return false
  const a = meta.value.fields
  const b = { ...form.value, tags: parseTags(), narrators: parseNarrators() }
  const changedCore = (Object.keys(a) as (keyof BookMetadataFields)[]).some((k) =>
    k === 'tags' || k === 'narrators'
      ? JSON.stringify(a[k]) !== JSON.stringify(b[k])
      : String(a[k]) !== String(b[k]),
  )
  return changedCore || customDirty.value
})

function fmt(v: string | string[]): string {
  return Array.isArray(v) ? v.join('、') : String(v ?? '')
}

function metaState(k: keyof BookMetadataFields) {
  return meta.value?.meta?.[k]
}

/** 该字段（或封面）是否被锁定。字段从 `meta` 读，封面从 `locked` 清单读 */
function isLocked(k: string): boolean {
  if (k === COVER) return !!meta.value?.locked?.includes(COVER)
  return metaState(k as keyof BookMetadataFields)?.locked === true
}

/**
 * 字段（含封面）的中文名。**全组件只此一份**。
 *
 * 早先这段 `k === COVER ? '封面' : FIELD_LABELS[k as keyof BookMetadataFields] ?? k`
 * 在脚本里抄了两遍、模板里抄了三遍；模板内联的那处（底部「实际改动」提示）在
 * `vue-tsc` 3.3.12 下直接报 TS2339（`Record` 上没有 `value`）—— 收敛到这里，
 * 索引 `FIELD_LABELS` 所需的断言只出现一次。
 * ⚠️ `k` 收 `string` 而不是 `keyof BookMetadataFields`：调用方会传 `changed`（抓取/清空
 * 回包给的 `string[]`，不保证是元数据字段键），落到 `?? k` 分支就是原样显示。
 */
function labelOf(k: string): string {
  if (k === COVER) return '封面'
  return FIELD_LABELS[k as keyof BookMetadataFields] ?? k
}

/** 「已锁定」徽标统一走这里，免得三处各写一遍判定 */
function lockTitle(k: string): string {
  const zh = labelOf(k)
  return isLocked(k)
    ? `已锁定「${zh}」：在线抓取不会改写它（手动编辑仍可用），点一下解锁`
    : `锁定「${zh}」：在线抓取永不改写它 —— 即使该字段策略是「总是覆盖」`
}

/**
 * 切换某个字段的锁。**只管抓取**：不写值、不撤销覆盖，因此不必 `emit('saved')`
 * （详情页展示的生效值一个字都没变）。
 */
async function toggleLock(k: string): Promise<void> {
  if (!meta.value || !editable.value) return
  const next = !isLocked(k)
  locking.value = k
  try {
    const r = await api.lockBookMetadata(props.bookId, k, next)
    // 用服务端回的清单整体覆盖：锁是「一份清单」而不是单字段的孤立状态
    meta.value = { ...meta.value, locked: r.locked_fields }
    if (k !== COVER) {
      const st = meta.value.meta[k as keyof BookMetadataFields]
      if (st) {
        meta.value = {
          ...meta.value,
          meta: { ...meta.value.meta, [k]: { ...st, locked: r.locked } },
        }
      }
    }
    const zh = labelOf(k)
    ui.toast(r.locked ? `已锁定「${zh}」：抓取不会再动它` : `已解锁「${zh}」：抓取可以重新接管`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '锁定失败')
  } finally {
    locking.value = ''
  }
}

/** 已覆盖字段的「在线建议值」提示文案 */
function onlineText(k: keyof BookMetadataFields): string {
  const s = metaState(k)
  if (s?.overridden) {
    const o = fmt(s.online)
    if (o) return `在线：${o}`
    // 撤掉覆盖之后这个字段还剩什么，取决于**它有没有 OPF 那一层** —— 不取决于格式：
    // 演播者 / 副标题 / 提供商 ID 在文件里根本没有对应元素，EPUB 也一样没有。
    // （早先按 `format === 'EPUB'` 判，对这几项说的是假话。）
    return DB_ONLY_FIELDS.has(k) || meta.value?.format !== 'EPUB'
      ? '（无在线建议，恢复后该字段为空）'
      : '（无在线建议，恢复后将回到文件原值）'
  }
  return ''
}

function parseTags(): string[] {
  return tagText.value
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** 演播者草稿解析（第 53 期，与题材同规则） */
function parseNarrators(): string[] {
  return narratorText.value
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

// ---------------- 自定义字段（第 35 期）----------------
// 值不落在 OPF 字段那套里，而是按**字段定义**存到 book_custom_values；
// 详情页只显示「该书所属书库适用且未归档」的定义（后端已筛好，这里照着渲染即可）。
// 编辑草稿是纯文本：`list` 类型也用「、」分隔的原文本提交 —— 后端负责切分并校验，
// 前端不自己拆（规则若在两端各写一遍，迟早会不一致）。
const customForm = ref<Record<string, string>>({})

function customToText(v: string | string[]): string {
  return Array.isArray(v) ? v.join('、') : String(v ?? '')
}

/** 用服务端下发的值重置草稿（加载 / 保存 / 恢复之后都要跟着走一遍） */
function resetCustom(): void {
  const out: Record<string, string> = {}
  for (const c of meta.value?.custom ?? []) out[c.key] = customToText(c.value)
  customForm.value = out
}

/** 自定义字段是否有改动（与 `dirty` 一起决定「保存」是否可点） */
const customDirty = computed(() =>
  (meta.value?.custom ?? []).some((c) => (customForm.value[c.key] ?? '') !== customToText(c.value)),
)

function customHint(c: { type: string }): string {
  if (c.type === 'list') return '多个值用「、」或逗号分隔'
  if (c.type === 'number') return '只接受数字'
  if (c.type === 'date') return '日期（如 2024-01-02）'
  return ''
}

async function save(): Promise<void> {
  if (!form.value || !meta.value) return
  saving.value = true
  try {
    const fields = { ...form.value, tags: parseTags(), narrators: parseNarrators() }
    // 自定义字段与 OPF 字段同批提交（同一张表单、同一个保存按钮）；没有定义时不带这个键
    const custom = (meta.value.custom ?? []).length ? { ...customForm.value } : undefined
    const r = await api.setBookMetadata(props.bookId, fields, custom)
    changed.value = r.changed
    if (r.unknown.length) {
      ui.toast(`已保存；不支持的字段已忽略：${r.unknown.join('、')}`)
    } else if (r.custom_ignored?.length) {
      ui.toast(`已保存；不适用的自定义字段已忽略：${r.custom_ignored.join('、')}`)
    } else {
      const n = r.changed.length + (r.custom_saved?.length ?? 0)
      ui.toast(n ? `已保存，实际改动 ${n} 项` : '没有实际改动')
    }
    // 用服务端回读的值刷新表单与分层明细（后端会做规整，如 3.00 → 3）
    meta.value = {
      ...meta.value,
      fields: { ...r.fields },
      meta: { ...r.meta },
      custom: r.custom ?? meta.value.custom,
    }
    form.value = { ...r.fields }
    tagText.value = (r.fields.tags || []).join('、')
    narratorText.value = (r.fields.narrators || []).join('、')
    resetCustom()
    emit('saved')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function restoreFields(fields: string[]): Promise<void> {
  if (!meta.value || !fields.length) return
  restoring.value = true
  try {
    const r = await api.revertBookMetadata(props.bookId, fields)
    meta.value = { ...meta.value, fields: { ...r.fields }, meta: { ...r.meta } }
    form.value = { ...r.fields }
    tagText.value = (r.fields.tags || []).join('、')
    narratorText.value = (r.fields.narrators || []).join('、')
    ui.toast(`已恢复 ${r.recovered.length} 个字段为在线值`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    restoring.value = false
  }
}

function restoreOne(k: keyof BookMetadataFields): void {
  void restoreFields([k])
}

/**
 * **显式清空**单个字段（提交 `null`）——与 `restoreOne` 相反：
 * 恢复是撤掉覆盖、回落到在线值或文件原值；清空是让这个字段真的没有值。
 */
async function clearOne(k: keyof BookMetadataFields): Promise<void> {
  if (!meta.value) return
  clearing.value = true
  try {
    const r = await api.setBookMetadata(props.bookId, { [k]: null } as BookMetadataWriteFields)
    meta.value = {
      ...meta.value,
      fields: { ...r.fields },
      meta: { ...r.meta },
      custom: r.custom ?? meta.value.custom,
    }
    form.value = { ...r.fields }
    tagText.value = (r.fields.tags || []).join('、')
    narratorText.value = (r.fields.narrators || []).join('、')
    resetCustom()
    ui.toast(r.changed.length ? `已清空：${labelOf(k)}` : '该字段本来就是空的')
    emit('saved')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '清空失败')
  } finally {
    clearing.value = false
  }
}

function restoreAll(): void {
  const fields = meta.value
    ? Object.keys(meta.value.meta).filter((f) => meta.value!.meta[f]?.overridden)
    : []
  void restoreFields(fields)
}

const INPUT_CLS =
  'h-8 w-full rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card'
</script>

<template>
  <div>
    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="meta && form">
      <Card padding="none" class="mb-3">
        <div class="border-b border-border px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-[13px] font-semibold text-foreground">编辑元数据</h3>
            <span class="font-mono text-[11px] text-muted-foreground">{{ meta.name }}</span>
            <span v-if="dirty" class="rounded bg-warning/14 px-1.5 py-0.5 text-[10.5px] text-warning">有未保存的改动</span>
          </div>
          <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
            改动存进应用数据库，书库列表、详情、搜索、OPDS 立即一致。
            <strong>不会改文件名，也不会改写书文件本身</strong>
            —— 用其它软件直读文件看到的是原始元数据；在线抓取默认优先覆盖本地，
            你手动改过的字段会被保护（标「已本地修改」），再抓取也不冲掉。
            两种撤销方式不一样：<strong>「恢复在线」</strong>是撤掉你的改动、回落到抓取结果或文件原值；
            <strong>「清空」</strong>是让这个字段真的没有值（之后抓取也不会把它填回来）。
            <strong>「锁定」</strong>又是另一回事：它不改变任何值，只是告诉抓取「这个字段别动」——
            即使该字段的策略写着「总是覆盖」也不会被改写；而手动编辑照旧可改。
            最下方的<strong>自定义字段</strong>是你在设置页定义过的字段，同样只存服务端；
            它们的值一起由这个「保存」提交。
          </p>
        </div>

        <div class="grid grid-cols-1 gap-x-4 px-4 py-3 sm:grid-cols-2">
          <!-- 分组标题用 `sm:col-span-2` 横跨两列；`<template>` 本身不渲染元素，
               所以网格里除标题外仍是平铺的字段 -->
          <template v-for="g in GROUPS" :key="g.title">
            <div class="border-b border-border pb-1.5 pt-1 sm:col-span-2">
              <span class="text-[11px] font-semibold uppercase tracking-wide text-foreground">
                {{ g.title }}
              </span>
              <span class="ml-2 text-[11px] text-muted-foreground">{{ g.hint }}</span>
            </div>
            <label
              v-for="k in g.fields"
              :key="k"
              class="flex flex-col gap-1 border-b border-border/60 py-2.5"
            >
              <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
                {{ labelOf(k) }}
                <span
                  v-if="meta.meta[k]?.overridden"
                  class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
                >已本地修改</span>
                <button
                  type="button"
                  :disabled="!editable || locking === k"
                  class="ml-auto flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors disabled:opacity-50"
                  :class="meta.meta[k]?.locked
                    ? 'bg-warning/14 text-warning'
                    : 'text-muted-foreground hover:text-foreground'"
                  :title="lockTitle(k)"
                  @click="toggleLock(k)"
                >
                  <Icon :name="meta.meta[k]?.locked ? 'lock' : 'unlock'" class="h-3 w-3" />
                  {{ meta.meta[k]?.locked ? '已锁定' : '锁定' }}
                </button>
              </span>
              <input v-model="form[k] as string" type="text" :disabled="!editable" :class="INPUT_CLS">
              <div
                v-if="meta.meta[k]?.overridden || fmt(form[k] as string)"
                class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
              >
                <button
                  v-if="meta.meta[k]?.overridden"
                  type="button"
                  :disabled="!editable || restoring || clearing"
                  class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                  @click="restoreOne(k)"
                >
                  ↺ 恢复在线
                </button>
                <button
                  type="button"
                  :disabled="!editable || clearing"
                  class="cursor-pointer rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                  @click="clearOne(k)"
                >
                  ✕ 清空
                </button>
                <span v-if="meta.meta[k]?.overridden" class="text-muted-foreground">{{ onlineText(k) }}</span>
              </div>
            </label>
          </template>

          <label class="flex flex-col gap-1 border-b border-border/60 py-2.5 sm:col-span-2">
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              题材（用「、」或逗号分隔，保存时自动去重）
              <span
                v-if="meta.meta.tags?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
              <button
                type="button"
                :disabled="!editable || locking === 'tags'"
                class="ml-auto flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors disabled:opacity-50"
                :class="meta.meta.tags?.locked
                  ? 'bg-warning/14 text-warning'
                  : 'text-muted-foreground hover:text-foreground'"
                :title="lockTitle('tags')"
                @click="toggleLock('tags')"
              >
                <Icon :name="meta.meta.tags?.locked ? 'lock' : 'unlock'" class="h-3 w-3" />
                {{ meta.meta.tags?.locked ? '已锁定' : '锁定' }}
              </button>
            </span>
            <input v-model="tagText" type="text" :disabled="!editable" :class="INPUT_CLS" placeholder="科幻 · 小说">
            <div
              v-if="meta.meta.tags?.overridden || tagText.trim()"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                v-if="meta.meta.tags?.overridden"
                type="button"
                :disabled="!editable || restoring || clearing"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne('tags')"
              >
                ↺ 恢复在线
              </button>
              <button
                type="button"
                :disabled="!editable || clearing"
                class="cursor-pointer rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                @click="clearOne('tags')"
              >
                ✕ 清空
              </button>
              <span v-if="meta.meta.tags?.overridden" class="text-muted-foreground">{{ onlineText('tags') }}</span>
            </div>
          </label>

          <!-- 演播者（第 53 期）：与题材同构的列表字段，用「、」或逗号分隔，保存时自动去重保序 -->
          <label class="flex flex-col gap-1 border-b border-border/60 py-2.5 sm:col-span-2">
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              演播者（用「、」或逗号分隔，保存时自动去重）
              <span
                v-if="meta.meta.narrators?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
              <button
                type="button"
                :disabled="!editable || locking === 'narrators'"
                class="ml-auto flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors disabled:opacity-50"
                :class="meta.meta.narrators?.locked
                  ? 'bg-warning/14 text-warning'
                  : 'text-muted-foreground hover:text-foreground'"
                :title="lockTitle('narrators')"
                @click="toggleLock('narrators')"
              >
                <Icon :name="meta.meta.narrators?.locked ? 'lock' : 'unlock'" class="h-3 w-3" />
                {{ meta.meta.narrators?.locked ? '已锁定' : '锁定' }}
              </button>
            </span>
            <input v-model="narratorText" type="text" :disabled="!editable" :class="INPUT_CLS" placeholder="张三、李四">
            <div
              v-if="meta.meta.narrators?.overridden || narratorText.trim()"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                v-if="meta.meta.narrators?.overridden"
                type="button"
                :disabled="!editable || restoring || clearing"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne('narrators')"
              >
                ↺ 恢复在线
              </button>
              <button
                type="button"
                :disabled="!editable || clearing"
                class="cursor-pointer rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                @click="clearOne('narrators')"
              >
                ✕ 清空
              </button>
              <span v-if="meta.meta.narrators?.overridden" class="text-muted-foreground">{{ onlineText('narrators') }}</span>
            </div>
          </label>

          <label class="flex flex-col gap-1 py-2.5 sm:col-span-2">
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              简介
              <span
                v-if="meta.meta.description?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
              <button
                type="button"
                :disabled="!editable || locking === 'description'"
                class="ml-auto flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors disabled:opacity-50"
                :class="meta.meta.description?.locked
                  ? 'bg-warning/14 text-warning'
                  : 'text-muted-foreground hover:text-foreground'"
                :title="lockTitle('description')"
                @click="toggleLock('description')"
              >
                <Icon :name="meta.meta.description?.locked ? 'lock' : 'unlock'" class="h-3 w-3" />
                {{ meta.meta.description?.locked ? '已锁定' : '锁定' }}
              </button>
            </span>
            <textarea
              v-model="form.description"
              rows="5"
              :disabled="!editable"
              class="w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
            />
            <div
              v-if="meta.meta.description?.overridden || form.description.trim()"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                v-if="meta.meta.description?.overridden"
                type="button"
                :disabled="!editable || restoring || clearing"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne('description')"
              >
                ↺ 恢复在线
              </button>
              <button
                type="button"
                :disabled="!editable || clearing"
                class="cursor-pointer rounded text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                @click="clearOne('description')"
              >
                ✕ 清空
              </button>
              <span v-if="meta.meta.description?.overridden" class="text-muted-foreground">{{ onlineText('description') }}</span>
            </div>
          </label>

          <!--
            封面：封面图不在 `fields` 里（它是 BLOB 缓存，不是文本字段），所以这里只给
            「抓取开关」不给值编辑 —— 值本身在详情页 hero 区展示。锁状态读 `meta.locked`。
          -->
          <div class="flex flex-wrap items-center gap-2 border-b border-border/60 py-2.5 sm:col-span-2">
            <span class="text-[11.5px] text-muted-foreground">封面（在线抓取替换）</span>
            <button
              type="button"
              :disabled="!editable || locking === COVER"
              class="flex cursor-pointer items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] transition-colors disabled:opacity-50"
              :class="isLocked(COVER)
                ? 'bg-warning/14 text-warning'
                : 'text-muted-foreground hover:text-foreground'"
              :title="lockTitle(COVER)"
              @click="toggleLock(COVER)"
            >
              <Icon :name="isLocked(COVER) ? 'lock' : 'unlock'" class="h-3 w-3" />
              {{ isLocked(COVER) ? '已锁定' : '锁定' }}
            </button>
            <span class="text-[11px] text-muted-foreground">
              锁上后在线抓取不会替换这张封面图。
            </span>
          </div>

          <!--
            自定义字段（第 35 期）：由**字段定义**驱动，只显示该书所属书库适用、且未归档的那些
            （后端已按适用书库筛好）。值存 book_custom_values，与上面的 OPF 字段是两套存储，
            但同属这一张表单、由同一个「保存」提交。
          -->
          <label
            v-for="c in meta.custom"
            :key="c.key"
            class="flex flex-col gap-1 border-b border-border/60 py-2.5"
          >
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              {{ c.label }}
              <span class="rounded bg-muted px-1.5 py-0.5 text-[10px]">自定义</span>
              <span v-if="customHint(c)" class="text-[10.5px]">{{ customHint(c) }}</span>
            </span>
            <input
              v-model="customForm[c.key]"
              :type="c.type === 'number' ? 'number' : 'text'"
              :disabled="!editable"
              :placeholder="c.default_value ? `默认：${c.default_value}` : ''"
              :class="INPUT_CLS"
            >
            <span
              v-if="!customForm[c.key] && c.default_value"
              class="text-[10.5px] text-muted-foreground"
            >
              留空即「没有值」；抓取会补上默认值 {{ c.default_value }}（已保存过值的不再补）
            </span>
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
          <span v-if="changed.length" class="text-[11.5px] text-muted-foreground">
            实际改动：{{ changed.map(labelOf).join('、') }}
          </span>
          <Button
            v-if="hasOverrides && editable"
            size="sm"
            variant="ghost"
            :disabled="restoring"
            class="ml-auto"
            @click="restoreAll"
          >
            ↺ 恢复全部为在线
          </Button>
          <Button
            size="sm"
            variant="primary"
            :disabled="!editable || saving || !dirty"
            :class="hasOverrides ? '' : 'ml-auto'"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </Button>
        </div>
      </Card>
    </template>
  </div>
</template>
