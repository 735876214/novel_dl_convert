<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import MetadataScoreCard from '@/components/MetadataScoreCard.vue'
import { api, type CustomFieldDef, type MetadataPlanItem, type MetadataSource } from '@/lib/api'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * 书库 → 元数据抓取与治理（7 个路由共用一个组件，靠 props.section 区分）
 *
 * 上游把这块拆成 Pages / Field Rules / Custom Fields / Confidence / Books / Authors /
 * Genre Blocklist 七页；本项目按同样的页面划分，但**配置是同一段**（`metadata_fetch`），
 * 所以各页只是同一份草稿的不同视图 —— 这也是它们共用 `saveSection('metadata')` 的原因。
 *
 * 抓取与写回**一律先预览、再应用**：预览只算不改，应用只提交你勾选过的具体值。
 */
const props = defineProps<{ section: string }>()

const ui = useUiStore()
const library = useLibraryStore()
const { cfg, val, setVal, saving, loadConfig, saveSection } = useSettingsConfig()

const SECTIONS: Record<string, { zh: string; en: string; desc: string; blocks: string[] }> = {
  providers: {
    zh: '元数据源', en: 'Providers', desc: '选择可用的元数据来源，并检测各自的连通性',
    blocks: ['switch', 'sources'],
  },
  'auto-fetch': {
    zh: '自动抓取', en: 'Books', desc: '入库时自动补全（仍受字段策略与置信度约束）',
    blocks: ['switch', 'fetch', 'panel'],
  },
  authors: {
    zh: '作者元数据', en: 'Authors', desc: '抓取作者传记与头像（在线优先、本地可覆盖）',
    blocks: ['authors'],
  },
  'field-rules': {
    zh: '字段规则', en: 'Field Rules', desc: '每个字段允许被怎样写入',
    blocks: ['fields'],
  },
  score: {
    zh: '置信度阈值', en: 'Confidence Score',
    desc: '元数据完整度评分模型与书库分布；下方阈值用于抓取候选的自动应用',
    blocks: ['score'],
  },
  'genre-blocklist': {
    zh: '题材黑名单', en: 'Genre Blocklist', desc: '命中这些词的题材不写入',
    blocks: ['blocklist'],
  },
  'custom-fields': {
    zh: '自定义字段', en: 'Custom Fields', desc: '存入应用数据库的自定义元数据',
    blocks: ['custom'],
  },
}

const meta = computed(() => SECTIONS[props.section] ?? { zh: '元数据', en: 'Metadata', desc: '', blocks: [] })
const mf = computed<Record<string, any>>(() => (cfg.value as any)?.metadata_fetch ?? {})
const has = (b: string) => meta.value.blocks.includes(b)

/** 可写字段（与后端 fileops.METADATA_FIELDS 对齐；显示名给人看，键名给 OPF 用） */
const FIELDS: Array<{ key: string; zh: string }> = [
  { key: 'title', zh: '书名' }, { key: 'author', zh: '作者' },
  { key: 'publisher', zh: '出版社' }, { key: 'date', zh: '出版年' },
  { key: 'language', zh: '语言' }, { key: 'isbn', zh: 'ISBN' },
  { key: 'description', zh: '简介' }, { key: 'tags', zh: '题材' },
  { key: 'cover', zh: '封面' },
]
/**
 * 字段写入策略。⚠️ 顺序与标注按**引擎真实默认**排：`metafetch.DEFAULT_POLICY = "overwrite"`
 * （第 8 期起改为「在线优先覆盖本地」，用户改过的字段另有保护），
 * 所以「总是覆盖」才是默认档 —— 别再写成「仅补空（推荐）」。
 */
const POLICIES = [
  { value: 'overwrite', label: '总是覆盖（默认）' },
  { value: 'fill_only', label: '仅补空（只在原值为空时写）' },
  { value: 'skip', label: '不修改' },
]

/** 字段键 → 中文名（预览区两处都用它，免得一处写 `FIELDS.find` 一处写死） */
function fieldZh(k: string): string {
  return FIELDS.find((f) => f.key === k)?.zh ?? k
}

const sources = ref<MetadataSource[]>([])
const probes = ref<Record<string, { ok: boolean; message: string; ms: number }>>({})
const probing = ref(false)

// ---------------- 作者元数据（第 8 期 D1/D2/D5）----------------
const af = computed<Record<string, any>>(() => mf.value.authors ?? {})
const authorFetching = ref(false)
const authorFetchResult = ref('')

async function runAuthorFetch(): Promise<void> {
  authorFetching.value = true
  authorFetchResult.value = ''
  try {
    const r = await api.fetchAllAuthors()
    authorFetchResult.value = `成功 ${r.ok} / 共 ${r.total}` + (r.failed ? `，失败 ${r.failed}` : '')
    ui.toast(`作者抓取完成：成功 ${r.ok} / 共 ${r.total}`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '作者抓取失败')
  } finally {
    authorFetching.value = false
  }
}

async function loadSources(): Promise<void> {
  try {
    sources.value = (await api.metadataSources()).items
  } catch { /* 未登录或后端未就绪：静默 */ }
}

async function probeAll(): Promise<void> {
  probing.value = true
  try {
    probes.value = { ...probes.value, ...(await api.metadataProbe()).items }
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '连通性检测失败')
  } finally {
    probing.value = false
  }
}

const activeSources = computed<string[]>(() => mf.value.sources ?? [])
function inOrder(id: string): boolean {
  return activeSources.value.includes(id)
}
function toggleSource(id: string): void {
  const cur = activeSources.value.slice()
  const i = cur.indexOf(id)
  if (i >= 0) cur.splice(i, 1)
  else cur.push(id)
  setVal('metadata_fetch.sources', cur)
}
function move(id: string, delta: number): void {
  const cur = activeSources.value.slice()
  const i = cur.indexOf(id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= cur.length) return
  ;[cur[i], cur[j]] = [cur[j], cur[i]]
  setVal('metadata_fetch.sources', cur)
}

// ---------------- 抓取面板（预览 → 应用）----------------
const planItems = ref<MetadataPlanItem[]>([])
const picked = ref<Set<string>>(new Set())
const running = ref(false)
const progress = ref({ done: 0, total: 0 })

/** 「有缺口」= 该补的书：缺封面 / 缺语言 / 缺出版社 / 缺简介（**不限格式** —— 抓取对非 EPUB 同样适用） */
const missing = computed(() =>
  library.books.filter(
    (b) => !b.has_cover || !b.language || !b.publisher || !b.description,
  ),
)

async function runPlan(): Promise<void> {
  const targets = missing.value
  if (!targets.length) {
    ui.toast('没有需要补全的书')
    return
  }
  running.value = true
  planItems.value = []
  picked.value = new Set()
  progress.value = { done: 0, total: targets.length }
  const acc: MetadataPlanItem[] = []
  try {
    // 逐本调用：每本要外呼每个源，一次全库必然超时；逐本还能实时显示进度
    for (const b of targets) {
      const r = await api.metadataPlan([b.name])
      acc.push(...(r.items ?? []))
      planItems.value = [...acc]
      progress.value = { done: progress.value.done + 1, total: targets.length }
    }
    picked.value = new Set(acc.filter((i) => !i.skipped && Object.keys(i.changes).length).map((i) => i.name))
    const withChanges = acc.filter((i) => Object.keys(i.changes).length || i.cover).length
    ui.toast(`预览完成：${withChanges} 本有可补内容`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '预览失败')
  } finally {
    running.value = false
  }
}

async function applyPicked(): Promise<void> {
  const items = planItems.value
    .filter((i) => picked.value.has(i.name))
    .map((i) => ({
      name: i.name,
      fields: Object.fromEntries(Object.entries(i.changes).map(([k, v]) => [k, (v as any).to])),
      cover: i.cover ? { url: i.cover.url } : null,
    }))
    .filter((i) => Object.keys(i.fields).length || i.cover)
  if (!items.length) {
    ui.toast('没有选中的可写条目')
    return
  }
  running.value = true
  try {
    const r = await api.metadataApply(items)
    ui.toast(`已写入 ${r.count} 本` + (r.covers ? `（含 ${r.covers} 张封面）` : '')
      + (r.failed.length ? `，${r.failed.length} 本失败` : ''))
    if (r.failed.length) console.warn('[metadata] 失败', r.failed)
    await library.loadBooks(true)
    planItems.value = []
    picked.value = new Set()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '写入失败')
  } finally {
    running.value = false
  }
}

function togglePick(name: string): void {
  const s = new Set(picked.value)
  if (s.has(name)) s.delete(name)
  else s.add(name)
  picked.value = s
}

function changeSummary(i: MetadataPlanItem): string {
  const names: Record<string, string> = Object.fromEntries(FIELDS.map((f) => [f.key, f.zh]))
  const keys = Object.keys(i.changes).map((k) => names[k] ?? k)
  if (i.cover) keys.push(i.cover.action === 'add' ? '封面（新增）' : '封面（替换）')
  return keys.join('、')
}
function short(v: unknown): string {
  if (Array.isArray(v)) return v.slice(0, 3).join(' / ')
  const s = String(v ?? '')
  return s.length > 28 ? s.slice(0, 28) + '…' : s
}

// ---------------- 自定义字段定义（第 35 期）----------------
// 定义存在应用数据库（不再是设置配置里的那串键值对），所以**本区改动立即生效**，
// 不走上方的「保存」（那条路只写配置文件）。每本书的值在详情页「编辑元数据」里填。
const defs = ref<CustomFieldDef[]>([])
const defsTrashed = ref<CustomFieldDef[]>([])
const defTypes = ref<Array<{ key: string; label: string }>>([])
const defBusy = ref(false)
const defDraft = ref({ label: '', type: 'text', default_value: '' })

async function loadDefs(): Promise<void> {
  try {
    const r = await api.customFields(true)
    defs.value = r.items
    defsTrashed.value = r.trashed ?? []
    defTypes.value = r.types
  } catch { /* 未登录 / 后端未就绪：与本节其它请求一样静默 */ }
}

/** 定义里的书库 id → 显示名（库被删掉时回落成 id，不隐藏） */
function libName(id: string): string {
  return library.libraryEntities.find((l) => l.id === id)?.name ?? id
}

async function createDef(): Promise<void> {
  const label = defDraft.value.label.trim()
  if (!label) {
    ui.toast('先填字段名')
    return
  }
  defBusy.value = true
  try {
    const r = await api.createCustomField({ ...defDraft.value, label })
    defs.value = r.items
    defDraft.value = { label: '', type: 'text', default_value: '' }
    ui.toast(`已新建字段「${r.item.label}」（键 ${r.item.key}）`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '新建失败')
  } finally {
    defBusy.value = false
  }
}

/** 改一项定义（label / 类型 / 默认值 / 归档 / 适用书库都会走到这里） */
async function patchDef(d: CustomFieldDef, patch: Record<string, unknown>): Promise<void> {
  defBusy.value = true
  try {
    defs.value = (await api.updateCustomField(d.id, patch)).items
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    defBusy.value = false
  }
}

function toggleDefLib(d: CustomFieldDef, lid: string): void {
  const cur = d.library_ids.slice()
  const i = cur.indexOf(lid)
  if (i >= 0) cur.splice(i, 1)
  else cur.push(lid)
  void patchDef(d, { library_ids: cur })
}

async function moveDef(d: CustomFieldDef, delta: number): Promise<void> {
  const ids = defs.value.map((x) => x.id)
  const i = ids.indexOf(d.id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  defBusy.value = true
  try {
    defs.value = (await api.reorderCustomFields(ids)).items
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '排序失败')
  } finally {
    defBusy.value = false
  }
}

async function trashDef(d: CustomFieldDef): Promise<void> {
  defBusy.value = true
  try {
    const r = await api.deleteCustomField(d.id)
    defs.value = r.items
    defsTrashed.value = r.trashed_items
    ui.toast(`「${d.label}」已移入垃圾桶（各本书上的值仍保留）`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  } finally {
    defBusy.value = false
  }
}

async function restoreDef(d: CustomFieldDef): Promise<void> {
  defBusy.value = true
  try {
    defs.value = (await api.restoreCustomField(d.id)).items
    defsTrashed.value = defsTrashed.value.filter((x) => x.id !== d.id)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    defBusy.value = false
  }
}

async function purgeDef(d: CustomFieldDef): Promise<void> {
  defBusy.value = true
  try {
    const r = await api.purgeCustomField(d.id)
    defs.value = r.items
    defsTrashed.value = r.trashed_items
    ui.toast(`「${d.label}」已彻底删除（所有书上的值一并清除）`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '彻底删除失败')
  } finally {
    defBusy.value = false
  }
}

onMounted(() => {
  void loadConfig()
  void loadSources()
  void library.loadBooks()
  if (props.section === 'custom-fields') void loadDefs()
})
/** 7 页共用组件：**必须监听 prop**，否则路由切换时组件实例被复用、数据不重载 */
watch(() => props.section, () => {
  void loadSources()
  planItems.value = []
  picked.value = new Set()
  defDraft.value = { label: '', type: 'text', default_value: '' }
  if (props.section === 'custom-fields') void loadDefs()
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ meta.zh }}</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">{{ meta.en }}</span>
      <span class="text-[11.5px] text-muted-foreground">{{ meta.desc }}</span>
      <Badge v-if="props.section === 'authors'" :tone="af.enabled ? 'accent' : undefined">
        {{ af.enabled ? '已启用' : '已关闭' }}
      </Badge>
      <Badge v-else-if="mf.enabled" tone="accent">已启用</Badge>
      <Badge v-else>已关闭</Badge>
      <Button size="sm" variant="primary" class="ml-auto" :disabled="saving || !cfg" @click="saveSection('metadata')">
        保存
      </Button>
    </div>

    <Card v-if="has('switch')" padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5 last:border-b-0">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">总开关</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            抓取会<strong>外呼公网</strong>（OpenLibrary / Google Books），故默认关闭
          </div>
        </div>
        <Button size="sm" :variant="mf.enabled ? 'ghost' : 'primary'" :disabled="saving"
                @click="setVal('metadata_fetch.enabled', !mf.enabled); saveSection('metadata')">
          {{ mf.enabled ? '关闭' : '开启' }}
        </Button>
      </div>
    </Card>

    <Card v-if="has('sources')" class="mt-4" padding="none">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">元数据源</span>
        <span class="text-[11.5px] text-muted-foreground">按顺序依次检索，单源失败不影响其它源</span>
        <Button size="sm" class="ml-auto" :disabled="probing" @click="probeAll">
          {{ probing ? '检测中…' : '检测连通性' }}
        </Button>
      </div>
      <div v-for="s in sources" :key="s.id" class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3 last:border-b-0">
        <input type="checkbox" class="h-4 w-4 cursor-pointer accent-primary"
               :checked="inOrder(s.id)" @change="toggleSource(s.id)" />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="text-[12.5px] font-medium text-foreground">{{ s.label }}</span>
            <Badge v-if="inOrder(s.id)">顺序 {{ activeSources.indexOf(s.id) + 1 }}</Badge>
          </div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">{{ s.note }}</div>
        </div>
        <span v-if="probes[s.id]" class="text-[11.5px]"
              :class="probes[s.id].ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'">
          {{ probes[s.id].ok ? '可用' : '不可用' }} · {{ probes[s.id].message }}
        </span>
        <Button size="sm" variant="ghost" :disabled="!inOrder(s.id)" @click="move(s.id, -1)">上移</Button>
        <Button size="sm" variant="ghost" :disabled="!inOrder(s.id)" @click="move(s.id, 1)">下移</Button>
        <a :href="s.home" target="_blank" rel="noreferrer" class="text-[11.5px] text-muted-foreground underline">官网</a>
      </div>
      <div class="border-t border-border px-4 py-3.5">
        <div class="mb-1.5 text-[12.5px] font-medium text-foreground">Google Books API Key（可选）</div>
        <div class="mb-2 text-[11.5px] text-muted-foreground">
          匿名额度很低（实测常撞 429），填 Key 可显著提高；掩码表示已设置，清空即删除
        </div>
        <input
          :value="val('metadata_fetch.googlebooks_api_key')"
          type="password" placeholder="未设置"
          class="w-[420px] max-w-full rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          @input="setVal('metadata_fetch.googlebooks_api_key', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </Card>

    <Card v-if="has('fetch')" class="mt-4" padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">入库时自动抓取</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            新书转好后自动抓取（异步执行、失败不影响入库；在线优先覆盖本地，你手动改过的字段受保护）
          </div>
        </div>
        <Button size="sm" :variant="mf.auto_on_import ? 'ghost' : 'primary'" :disabled="saving"
                @click="setVal('metadata_fetch.auto_on_import', !mf.auto_on_import); saveSection('metadata')">
          {{ mf.auto_on_import ? '关闭' : '开启' }}
        </Button>
      </div>
      <div class="flex flex-wrap items-center gap-3 px-4 py-3.5">
        <span class="text-[12.5px] text-foreground">每个源取候选数</span>
        <input :value="val('metadata_fetch.limit')" type="number" min="1" max="20"
               class="w-20 rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
               @input="setVal('metadata_fetch.limit', Number(($event.target as HTMLInputElement).value))" />
        <span class="text-[11.5px] text-muted-foreground">越多越慢（每个源都会外呼一次）</span>
      </div>
    </Card>

    <Card v-if="has('authors')" class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">作者元数据</span>
          <Badge v-if="af.enabled" tone="accent">已启用</Badge>
          <Badge v-else>已关闭</Badge>
          <Button size="sm" class="ml-auto" :disabled="authorFetching" @click="runAuthorFetch">
            {{ authorFetching ? '抓取中…' : '立即抓取全部作者' }}
          </Button>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          从 OpenLibrary 抓取作者传记与头像。头像会下载到本地缓存（零外链），由后端统一分发；
          抓取到的值优先使用，你手动改过的传记 / 头像会被保护，可随时恢复在线。
        </div>
        <div v-if="authorFetchResult" class="mt-1 text-[11.5px] text-muted-foreground">
          {{ authorFetchResult }}
        </div>
      </div>
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] text-foreground">启用作者抓取</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            独立于上方书籍抓取的开关；关闭后仍可用上面的按钮手动触发单次抓取
          </div>
        </div>
        <Button size="sm" :variant="af.enabled ? 'ghost' : 'primary'" :disabled="saving"
                @click="setVal('metadata_fetch.authors.enabled', !af.enabled); saveSection('metadata')">
          {{ af.enabled ? '关闭' : '开启' }}
        </Button>
      </div>
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] text-foreground">抓取传记</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">OpenLibrary 作者简介</div>
        </div>
        <Button size="sm" :variant="af.fetch_bio !== false ? 'ghost' : 'primary'" :disabled="saving"
                @click="setVal('metadata_fetch.authors.fetch_bio', af.fetch_bio === false)">
          {{ af.fetch_bio !== false ? '已开启' : '已关闭' }}
        </Button>
      </div>
      <div class="flex items-center gap-4 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] text-foreground">抓取头像</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">下载到本地缓存后由后端分发</div>
        </div>
        <Button size="sm" :variant="af.fetch_photo !== false ? 'ghost' : 'primary'" :disabled="saving"
                @click="setVal('metadata_fetch.authors.fetch_photo', af.fetch_photo === false)">
          {{ af.fetch_photo !== false ? '已开启' : '已关闭' }}
        </Button>
      </div>
    </Card>

    <Card v-if="has('panel')" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">手动抓取</span>
        <span class="text-[11.5px] text-muted-foreground">
          针对「有缺口」的书（缺封面 / 语言 / 出版社 / 简介），共 {{ missing.length }} 本
        </span>
        <div class="ml-auto flex items-center gap-2">
          <span v-if="running && progress.total" class="text-[11.5px] text-muted-foreground">
            {{ progress.done }} / {{ progress.total }}
          </span>
          <Button size="sm" :disabled="running || !mf.enabled" @click="runPlan">
            {{ running ? '处理中…' : '开始预览' }}
          </Button>
          <Button size="sm" variant="primary" :disabled="running || !picked.size" @click="applyPicked">
            应用选中（{{ picked.size }}）
          </Button>
        </div>
      </div>
      <div v-if="!mf.enabled" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        先在上方「总开关」里启用抓取。
      </div>
      <div v-else-if="!planItems.length" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        点「开始预览」后，这里会逐本列出候选与将要写入的内容 —— 预览<strong>不会改动任何文件</strong>。
      </div>
      <div v-else class="max-h-[520px] overflow-auto">
        <table class="w-full text-[12px]">
          <thead class="sticky top-0 bg-card text-left text-muted-foreground">
            <tr>
              <th class="w-8 px-3 py-2" />
              <th class="px-3 py-2">书</th>
              <th class="px-3 py-2">最佳候选</th>
              <th class="px-3 py-2">将写入</th>
              <th class="w-24 px-3 py-2">置信度</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in planItems" :key="i.name" class="border-t border-border/60">
              <td class="px-3 py-2 align-top">
                <input type="checkbox" class="h-4 w-4 cursor-pointer accent-primary disabled:opacity-40"
                       :disabled="!!i.skipped || (!Object.keys(i.changes).length && !i.cover)"
                       :checked="picked.has(i.name)" @change="togglePick(i.name)" />
              </td>
              <td class="px-3 py-2 align-top">
                <div class="text-foreground">{{ i.title || i.name }}</div>
                <div class="text-[11px] text-muted-foreground">{{ i.name }}</div>
              </td>
              <td class="px-3 py-2 align-top">
                <template v-if="i.candidates.length">
                  <div class="text-foreground">{{ i.candidates[0].title }}</div>
                  <div class="text-[11px] text-muted-foreground">
                    {{ i.candidates[0].author || '—' }}
                    <span v-if="i.candidates[0].publisher"> · {{ i.candidates[0].publisher }}</span>
                    · {{ i.candidates[0].source }}
                  </div>
                </template>
                <span v-else class="text-[11px] text-muted-foreground">
                  {{ i.skipped || i.error || '没有候选' }}
                </span>
              </td>
              <td class="px-3 py-2 align-top">
                <div v-if="Object.keys(i.changes).length" class="text-[11.5px]">
                  <div v-for="(v, k) in i.changes" :key="k" class="text-muted-foreground">
                    <span class="text-foreground">{{ fieldZh(k) }}</span>：
                    {{ short((v as any).to) }}
                  </div>
                </div>
                <div v-else-if="i.cover" class="text-[11.5px] text-muted-foreground">仅封面</div>
                <div v-else class="text-[11.5px] text-muted-foreground">无改动</div>
                <div v-if="i.cover && Object.keys(i.changes).length" class="mt-0.5 text-[11px] text-muted-foreground">
                  + 封面（{{ i.cover.action === 'add' ? '新增' : '替换' }}）
                </div>
                <!-- 锁比字段策略更硬：被锁的字段压根不会出现在上面，这里如实说明是「锁住了」而非「没抓到」 -->
                <div v-if="i.locked?.length" class="mt-0.5 text-[11px] text-warning">
                  ⚿ 已锁定、抓取不改：{{ i.locked.map(fieldZh).join('、') }}
                </div>
              </td>
              <td class="px-3 py-2 align-top">
                <span :class="i.auto_ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'">
                  {{ Math.round(i.best_score * 100) }}%
                </span>
                <div v-if="!i.auto_ok && i.candidates.length" class="text-[10.5px] text-muted-foreground">低于阈值</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <MetadataScoreCard v-if="has('score')" class="mt-4" />

    <Card v-if="has('score')" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-3 px-4 py-3.5">
        <div class="min-w-[240px] flex-1">
          <div class="text-[13px] font-medium text-foreground">抓取候选阈值</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            书名权重 0.7 + 作者 0.3（与「重复书籍」同一套相似度）；低于它的候选只列出、不自动写入。
            注意：这是<strong>抓取匹配分</strong>，与上方的<strong>元数据完整度</strong>是两件事。
          </div>
        </div>
        <input :value="val('metadata_fetch.threshold')" type="number" min="0.1" max="1" step="0.05"
               class="w-24 rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
               @input="setVal('metadata_fetch.threshold', Number(($event.target as HTMLInputElement).value))" />
      </div>
    </Card>

    <Card v-if="has('fields')" class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="text-[13px] font-medium text-foreground">字段写入策略</div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          这里定的是<strong>按库的默认</strong>。单本书还能在详情页「编辑元数据」里对某个字段
          <strong>上锁</strong>—— 锁比这里的策略更硬：即使选了「总是覆盖」，被锁的字段也不会被改写。
        </div>
      </div>
      <div v-for="f in FIELDS" :key="f.key"
           class="flex items-center gap-3 border-b border-border px-4 py-2.5 last:border-b-0">
        <span class="w-24 text-[12.5px] text-foreground">{{ f.zh }}</span>
        <span class="w-28 font-mono text-[11px] text-muted-foreground">{{ f.key }}</span>
        <select
          :value="(mf.fields ?? {})[f.key] ?? 'overwrite'"
          class="rounded-md border border-border bg-muted px-3 py-1.5 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          @change="setVal(`metadata_fetch.fields.${f.key}`, ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="p in POLICIES" :key="p.value" :value="p.value">{{ p.label }}</option>
        </select>
      </div>
    </Card>

    <Card v-if="has('blocklist')" class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="text-[13px] font-medium text-foreground">题材黑名单</div>
        <div class="mt-0.5 text-[11.5px] text-muted-foreground">
          每行一个词（大小写不敏感）。抓到的题材命中即丢弃 —— 用来滤掉「小说」「Fiction」这类没有信息量的值
        </div>
      </div>
      <div class="px-4 py-3.5">
        <textarea
          :value="(mf.genre_blocklist ?? []).join('\n')" rows="6"
          class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
          @input="setVal('metadata_fetch.genre_blocklist', ($event.target as HTMLTextAreaElement).value.split('\n').map((s) => s.trim()).filter(Boolean))"
        />
      </div>
    </Card>

    <Card v-if="has('custom')" class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="text-[13px] font-medium text-foreground">自定义字段</div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          定义字段本身（名字 / 类型 / 适用书库 / 默认值 / 顺序 / 归档）。
          <strong>本区改动立即生效</strong>，不走上方的「保存」。
          每本书的值在详情页「编辑元数据」里填；抓取只会给<strong>还没有值</strong>的书补默认值
          —— 清空成空值也算「填过了」，不会再被补回来。
        </div>
      </div>

      <!-- 新建：字段名是必填，key 由它派生（显示名改了不影响已存的值的归属） -->
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <input
          v-model="defDraft.label"
          placeholder="字段名（如 目录号）"
          class="h-8 w-52 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        >
        <select
          v-model="defDraft.type"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
          <option v-for="t in defTypes" :key="t.key" :value="t.key">{{ t.label }}</option>
        </select>
        <input
          v-model="defDraft.default_value"
          placeholder="默认值（可空；空则不参与抓取）"
          class="h-8 min-w-[12rem] flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        >
        <Button size="sm" variant="primary" :disabled="defBusy" @click="createDef">新建字段</Button>
      </div>

      <div v-if="!defs.length" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        还没有自定义字段。
      </div>
      <div v-for="(d, idx) in defs" :key="d.id" class="border-b border-border px-4 py-3 last:border-b-0">
        <div class="flex flex-wrap items-center gap-2">
          <input
            :value="d.label"
            class="h-8 w-52 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            @change="patchDef(d, { label: ($event.target as HTMLInputElement).value })"
          >
          <span class="font-mono text-[11px] text-muted-foreground">{{ d.key }}</span>
          <Badge v-if="d.archived">已归档</Badge>
          <div class="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" :disabled="defBusy || idx === 0" @click="moveDef(d, -1)">上移</Button>
            <Button size="sm" variant="ghost" :disabled="defBusy || idx === defs.length - 1" @click="moveDef(d, 1)">下移</Button>
            <Button size="sm" variant="ghost" :disabled="defBusy" @click="patchDef(d, { archived: !d.archived })">
              {{ d.archived ? '取消归档' : '归档' }}
            </Button>
            <Button size="sm" variant="ghost" :disabled="defBusy" @click="trashDef(d)">移入垃圾桶</Button>
          </div>
        </div>

        <div class="mt-2 flex flex-wrap items-center gap-2">
          <select
            :value="d.type"
            class="h-8 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
            @change="patchDef(d, { type: ($event.target as HTMLSelectElement).value })"
          >
            <option v-for="t in defTypes" :key="t.key" :value="t.key">{{ t.label }}</option>
          </select>
          <input
            :value="d.default_value"
            placeholder="默认值（抓取补空用；留空则不参与抓取）"
            class="h-8 min-w-[12rem] flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
            @change="patchDef(d, { default_value: ($event.target as HTMLInputElement).value })"
          >
        </div>

        <div class="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
          <span>适用书库（都不选 = 全部书库）</span>
          <button
            v-for="l in library.libraryEntities"
            :key="l.id"
            type="button"
            class="cursor-pointer rounded-md border px-2 py-0.5 text-[11px] transition-colors"
            :class="d.library_ids.includes(l.id)
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border hover:text-foreground'"
            @click="toggleDefLib(d, l.id)"
          >
            {{ l.name }}
          </button>
          <span v-if="!library.libraryEntities.length" class="text-[11px]">（还没有书库）</span>
          <!-- 库先删、定义后改的历史 id：如实标出来（写入端只收真实存在的库 id） -->
          <span
            v-for="id in d.library_ids.filter((x: string) => !library.libraryEntities.some((l) => l.id === x))"
            :key="id"
            class="rounded-md border border-warning/40 px-2 py-0.5 text-[11px] text-warning"
          >
            {{ libName(id) }}（书库已不存在）
          </span>
        </div>
      </div>

      <!-- 垃圾桶：软删的字段定义（值保留），恢复即完整还原；彻底删除会连带清掉所有书上的值 -->
      <div v-if="defsTrashed.length" class="border-t border-border px-4 py-3">
        <div class="mb-1.5 text-[12.5px] font-medium text-foreground">垃圾桶</div>
        <div class="mb-2 text-[11px] text-muted-foreground">
          恢复后各本书上的值原样回来；「彻底删除」不可恢复，并会清掉所有书上的值
        </div>
        <div v-for="d in defsTrashed" :key="d.id" class="flex flex-wrap items-center gap-2 py-1.5">
          <span class="text-[12.5px] text-muted-foreground">
            {{ d.label }}
            <span class="ml-2 font-mono text-[11px]">{{ d.key }}</span>
          </span>
          <div class="ml-auto flex items-center gap-1">
            <Button size="sm" variant="ghost" :disabled="defBusy" @click="restoreDef(d)">恢复</Button>
            <Button size="sm" variant="ghost" :disabled="defBusy" @click="purgeDef(d)">彻底删除</Button>
          </div>
        </div>
      </div>
    </Card>

    <SettingsUnsupportedCard
      class="mt-4"
      :label="`元数据 · ${meta.zh}`"
      :groups="['PROVIDERS', 'RULES', 'SCORE']"
      :items="[
        '元数据源插件市场 / 更多第三方源（当前内置 OpenLibrary 与 Google Books）',
        '系列级元数据（当前只写单本）',
      ]"
      note="已实现：源选择与顺序、连通性自检、Google Books API Key、入库自动抓取、ISBN 精确匹配、字段级写入策略、字段级锁定（单本书逐字段 / 封面，只挡抓取）、置信度阈值、题材黑名单、自定义字段（定义管理 + 按书的值 + 抓取补默认值）、「先预览再应用」的手动抓取面板，以及作者传记 / 头像抓取与本地覆盖编辑。"
    />
  </div>
</template>
