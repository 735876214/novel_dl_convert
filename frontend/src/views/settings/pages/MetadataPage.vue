<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import MetadataScoreCard from '@/components/MetadataScoreCard.vue'
import { api, type CustomFieldDef, type MetadataConfigField, type MetadataHealthResult,
         type MetadataPlanItem, type MetadataProvider } from '@/lib/api'
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

/** 提供商目录（第 57 期）：分四组；未实现的家只列出、不给开关 */
const providers = ref<MetadataProvider[]>([])
const providersLoading = ref(false)
/** 目录加载失败/回落的原因（**不静默**：空列表必须能解释自己） */
const providersError = ref('')
const probes = ref<Record<string, { ok: boolean; message: string; ms: number }>>({})
const probing = ref(false)

/** 目录总数：正常取到目录就用目录长度；回落旧接口时退化用「已启用条数」，避免显示 `N/0` */
const providerTotal = computed(() => providers.value.length || activeSources.value.length)

/** 过滤器（对齐上游那页的「全部 / 已启用 / 需要设置」）+ 搜索框 */
const PROV_FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '已启用' },
  { key: 'needs', label: '需要设置' },
] as const
const provFilter = ref<'all' | 'active' | 'needs'>('all')
const provQuery = ref('')

// ---------------- 行内「配置」（密钥搬到对应提供商那一行）----------------
// 形态对齐上游那页：每行右侧「配置 ▾」，展开后在**该行下方**给凭据输入 + 「测试」。
// 测试用**输入框里的当前值**（后端 `keys` 覆盖、不落盘）；只有「保存」才写进配置，
// 所以「改一下试试」不会污染已保存的凭据，也不会为了测试先保存一次。
const openConfig = ref<Set<string>>(new Set())
/** 草稿：键 = `${源 id}.${配置键名}` —— **只有用户改过才发**（没改就沿用已保存值，
 *  绝不把掩码当密钥写回去；空串也算「改过」= 本次按清空 / 回落默认处理） */
const draft = ref<Record<string, string>>({})
const rowBusy = ref<Record<string, boolean>>({})

/** 该行有可配置项才显示「配置」（项由注册表 `config_fields` 声明） */
function hasConfigSection(p: MetadataProvider): boolean {
  return (p.config_fields?.length ?? 0) > 0
}
function toggleConfig(id: string): void {
  const next = new Set(openConfig.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  openConfig.value = next
}
function fieldKey(sid: string, key: string): string {
  return `${sid}.${key}`
}
function setDraft(sid: string, key: string, v: string): void {
  draft.value = { ...draft.value, [fieldKey(sid, key)]: v }
  // 同时写进**页面级配置草稿**：这样页面自己的「保存」也能把行内改动一起落库。
  // （否则行内改动只存在于组件局部，用户点页面的「保存」会以为存了、其实没存。）
  // 静默态（用户没动过的 secret）不会被写进来 —— 它仍是后端的掩码值，而掩码值
  // 在后端是「不修改」语义（见 server 的 _KEY_MASK 注释），所以不会被覆盖成掩码字符串。
  setVal(`metadata_fetch.${key}`, v)
}
/** 控件当前值：改过 → 草稿；没改 → select 显示已保存值、secret 留空（占位符提示已设置） */
function fieldValue(p: MetadataProvider, f: MetadataConfigField): string {
  const d = draft.value[fieldKey(p.id, f.key)]
  if (d !== undefined) return d
  return f.type === 'select' ? String(val(`metadata_fetch.${f.key}`) || '') : ''
}
/** 该行**被改过**的字段（只有这些会被发送/保存） */
function rowDrafts(p: MetadataProvider): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of p.config_fields ?? []) {
    const k = fieldKey(p.id, f.key)
    if (k in draft.value) out[f.key] = draft.value[k]
  }
  return out
}
function rowIsBusy(id: string): boolean {
  return rowBusy.value[id] === true
}
function setRowBusy(id: string, v: boolean): void {
  rowBusy.value = { ...rowBusy.value, [id]: v }
}

/** 行内「测试」：把输入框里的当前值带给后端试一次（不改配置、不落盘） */
async function testRow(p: MetadataProvider): Promise<void> {
  setRowBusy(p.id, true)
  try {
    const drafts = rowDrafts(p)
    const configs = Object.keys(drafts).length ? { [p.id]: drafts } : undefined
    probes.value = { ...probes.value, ...(await api.metadataProbe([p.id], undefined, configs)).items }
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '测试失败')
  } finally {
    setRowBusy(p.id, false)
  }
}

/** 「重置」该行：所有字段置空并保存（secret = 删除；select = 回落 fetcher 默认） */
async function clearRow(p: MetadataProvider): Promise<void> {
  for (const f of p.config_fields ?? []) setDraft(p.id, f.key, '')
  await saveRow(p)
}

/** 保存该行被改过的字段（空串 = 清除 / 回落默认）；保存后重拉目录刷新状态 */
async function saveRow(p: MetadataProvider): Promise<void> {
  const changed = rowDrafts(p)
  if (!Object.keys(changed).length) {
    ui.toast('没有改动')
    return
  }
  setRowBusy(p.id, true)
  try {
    for (const [key, value] of Object.entries(changed)) {
      setVal(`metadata_fetch.${key}`, value)
    }
    await saveSection('metadata')
    const rest = { ...draft.value }
    for (const key of Object.keys(changed)) delete rest[fieldKey(p.id, key)]
    draft.value = rest                          // 已落库 ⇒ 清草稿，控件回到「未改」态
    await loadProviders()
    ui.toast('已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    setRowBusy(p.id, false)
  }
}

/** 按分组过滤后的可见条目（组内保持注册表顺序） */
const filteredGroups = computed(() => {
  const q = provQuery.value.trim().toLowerCase()
  const hit = (p: MetadataProvider): boolean => {
    if (provFilter.value === 'active' && !inOrder(p.id)) return false
    if (provFilter.value === 'needs' && !p.needs_setup) return false
    if (!q) return true
    return `${p.label} ${p.group} ${p.note}`.toLowerCase().includes(q)
  }
  const order: string[] = []
  const bucket: Record<string, MetadataProvider[]> = {}
  for (const p of providers.value) {
    if (!hit(p)) continue
    const g = p.group || '其它'
    if (!bucket[g]) {
      bucket[g] = []
      order.push(g)
    }
    bucket[g].push(p)
  }
  return order.map((name) => ({ name, items: bucket[name] }))
})

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

async function loadProviders(): Promise<void> {
  providersLoading.value = true
  providersError.value = ''
  try {
    providers.value = (await api.metadataProviders()).items
  } catch (e) {
    // ⚠️ 失败**不能静默**：第 57 期曾在旧后端（没有 /api/metadata/providers）下静默变空，
    // 用户看到的是「已启用：2/0 + 没有匹配的提供商」这种一头雾水的空列表。
    // 两道兜底：① 回落旧接口 /api/metadata/sources（一直存在）保住列表；
    // ② 把原因写在界面上（含「重启后端」这种要用户动手的动作）。
    try {
      const legacy = await api.metadataSources()
      const activeIds = legacy.items.filter((s) => s.active).map((s) => s.id)
      providers.value = legacy.items.map((s) => ({
        id: s.id,
        label: s.label,
        group: '元数据来源',
        home: s.home,
        note: s.note,
        implemented: true,
        fragile: false,
        needs_config: false,
        needs_setup: false,
        active: s.active,
        order: activeIds.indexOf(s.id) + 1,
        has_config: false,
      }))
      providersError.value = '未能读取完整的提供商目录（后端可能是旧版本）：已回落读取旧接口，'
        + '分组、易失效标记与密钥区暂不可用 —— 重启后端进程后刷新即可。'
    } catch {
      providers.value = []
      providersError.value = e instanceof Error ? e.message : '提供商目录加载失败'
    }
  } finally {
    providersLoading.value = false
  }
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

// ---------------- 真联网体检（第 59 期）----------------
// 一次看清「谁能用、谁为什么不能用」：「检测连通性」只回可用/不可用，
// 体检回的是**分类**（限流 / 拒绝 / 反爬拦截 / 能连通但解析不到 / 未填密钥），
// 因为这几件事要求用户做的动作完全不同（等一会 / 降频率 / 填 Key / 等修复）。
const health = ref<MetadataHealthResult | null>(null)
const healthQuery = ref('')
const healthRunning = ref(false)

/** 结论 → 颜色：绿=能出结果；灰=只是没配密钥；琥珀=等一会或站点可能改版；红=被拒/异常 */
function healthClass(kind: string): string {
  if (kind === 'ok') return 'text-emerald-600 dark:text-emerald-400'
  if (kind === 'missing_key') return 'text-muted-foreground'
  if (kind === 'empty' || kind === 'rate_limited') return 'text-amber-600 dark:text-amber-400'
  return 'text-destructive'
}

async function runHealth(): Promise<void> {
  healthRunning.value = true
  try {
    health.value = await api.metadataHealth(healthQuery.value.trim() || undefined)
    const s = health.value.summary
    ui.toast(`体检完成：可用 ${s.usable ?? 0} / 待处理 ${s.problems ?? 0}`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '体检失败')
  } finally {
    healthRunning.value = false
  }
}

/** 回看上次体检结果（后端进程内缓存；没体检过是常态，失败静默） */
async function loadHealth(): Promise<void> {
  try {
    health.value = await api.metadataHealthLast()
  } catch { /* 未登录 / 后端未就绪：静默 */ }
}

const activeSources = computed<string[]>(() => mf.value.sources ?? [])
function inOrder(id: string): boolean {
  return activeSources.value.includes(id)
}
/** 启用顺序（1 起；0 = 未启用）。开关与顺序都**只读配置草稿** —— 未保存前也即时可见 */
function orderOf(id: string): number {
  const i = activeSources.value.indexOf(id)
  return i >= 0 ? i + 1 : 0
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
/** 预览时**配置里的**来源顺序（后端随结果回传）：用来判断某本的 `sources_order` 是否被重排过 */
const planConfiguredOrder = ref<string[]>([])

/** 语种短码 → 中文名（提供商行标「韩语 / 波兰语 / …」） */
const LANG_ZH: Record<string, string> = {
  zh: '中文', en: '英语', ja: '日语', ko: '韩语', pl: '波兰语',
  fr: '法语', de: '德语', ru: '俄语', es: '西班牙语', it: '意大利语',
}
/** 语种亲和徽标：专精某语种 → 「韩语」；多语种通吃 → 「多语种」；两者都没有 → 空 */
function langBadge(p: MetadataProvider): string {
  const langs = p.langs ?? []
  if (langs.length) return langs.map((c) => LANG_ZH[c] || c).join('/')
  return p.lang_broad ? '多语种' : ''
}

/** 本书的检索顺序是否被「按语种重排」改过（与配置顺序逐位比较） */
function reordered(i: MetadataPlanItem): boolean {
  const cfg = planConfiguredOrder.value
  const o = i.sources_order ?? []
  return cfg.length > 0 && o.join('|') !== cfg.join('|')
}

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
      if (r.sources?.length) planConfiguredOrder.value = r.sources
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
  void loadProviders()
  void library.loadBooks()
  if (props.section === 'providers') void loadHealth()
  if (props.section === 'custom-fields') void loadDefs()
})
/** 7 页共用组件：**必须监听 prop**，否则路由切换时组件实例被复用、数据不重载 */
watch(() => props.section, () => {
  void loadProviders()
  if (props.section === 'providers') void loadHealth()
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

    <!--
      提供商（第 57 期）：按上游「设置 → 书库 → 元数据 → 提供商」那页重做 ——
      分组列出全部提供商（14 家），逐家给状态 / 配置 / 开关。
      ⚠️ 目录拉取失败时**不静默变空**：回落旧接口 + 在界面上写明原因（含「重启后端」）。
    -->
    <Card v-if="has('sources')" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">提供商</span>
        <Badge tone="accent">已启用：{{ activeSources.length }}/{{ providerTotal }}</Badge>
        <span class="text-[11.5px] text-muted-foreground">按顺序依次检索，单源失败不影响其它源</span>
        <input
          v-model="provQuery"
          type="text"
          placeholder="搜索提供商…"
          class="ml-auto h-7 w-[170px] rounded-md border border-border bg-muted px-2.5 text-[11.5px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
        <div class="flex items-center gap-1">
          <button
            v-for="f in PROV_FILTERS"
            :key="f.key"
            type="button"
            class="cursor-pointer rounded-full px-2.5 py-1 text-[11.5px] transition-colors"
            :class="provFilter === f.key
              ? 'bg-primary/12 text-primary'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="provFilter = f.key"
          >
            {{ f.label }}
          </button>
        </div>
        <Button size="sm" :disabled="probing" @click="probeAll">
          {{ probing ? '检测中…' : '检测连通性' }}
        </Button>
      </div>

      <!-- 目录没取全时说清楚为什么（旧后端 / 未登录 / 网络），并给一键重试 -->
      <div
        v-if="providersError"
        class="flex flex-wrap items-center gap-2 border-b border-border bg-warning/10 px-4 py-2 text-[11.5px] text-foreground"
      >
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>{{ providersError }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" :disabled="providersLoading" @click="loadProviders">
          重试
        </Button>
      </div>

      <div v-for="g in filteredGroups" :key="g.name" class="border-b border-border last:border-b-0">
        <div class="bg-muted/40 px-4 py-1.5 text-[11px] font-semibold text-muted-foreground">
          {{ g.name }}
        </div>
        <div
          v-for="p in g.items"
          :key="p.id"
          class="border-b border-border last:border-b-0"
        >
          <div class="flex flex-wrap items-center gap-3 px-4 py-3">
            <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-[11px] font-semibold text-foreground">
              {{ p.label.slice(0, 1) }}
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-[12.5px] font-medium text-foreground">{{ p.label }}</span>
                <Badge v-if="inOrder(p.id)" tone="accent">启用</Badge>
                <Badge v-if="orderOf(p.id)">顺序 {{ orderOf(p.id) }}</Badge>
                <!-- 语种亲和（第 60 期）：让「按语种重排」的结果可预期（这家会排在哪一档） -->
                <span
                  v-if="langBadge(p)"
                  class="rounded-full bg-muted px-2 py-0.5 text-[10.5px] text-muted-foreground"
                  :title="langBadge(p) === '多语种' ? '多语种通吃：任何语种都排在不相关专精之前'
                                                     : `专精 ${langBadge(p)}：书的语种与之相同时排最前`"
                >
                  {{ langBadge(p) }}
                </span>
                <!-- 页面抓取型：站点改版就可能失效 —— 如实标出来，别让用户以为是自己的问题 -->
                <span
                  v-if="p.fragile"
                  class="rounded-full bg-muted px-2 py-0.5 text-[10.5px] text-muted-foreground"
                  title="页面抓取型：站点改版后可能失效"
                >
                  易失效
                </span>
                <span
                  v-if="p.needs_setup"
                  class="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10.5px] text-amber-600 dark:text-amber-400"
                >
                  需要设置
                </span>
                <Badge v-if="!p.implemented">未接入</Badge>
              </div>
              <div class="mt-0.5 text-[11.5px] text-muted-foreground">{{ p.note }}</div>
              <div v-if="!p.implemented" class="mt-0.5 text-[11px] text-muted-foreground">
                本项目尚未实现该家的抓取器，不会出现在抓取计划里。
              </div>
              <div v-else-if="p.config_hint && !p.has_config" class="mt-0.5 text-[11px] text-muted-foreground">
                {{ p.config_hint }}
              </div>
            </div>
            <span
              v-if="probes[p.id]"
              class="text-[11.5px]"
              :class="probes[p.id].ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-destructive'"
            >
              {{ probes[p.id].ok ? '可用' : '不可用' }} · {{ probes[p.id].message }}
            </span>
            <Button size="sm" variant="ghost" :disabled="!inOrder(p.id)" @click="move(p.id, -1)">上移</Button>
            <Button size="sm" variant="ghost" :disabled="!inOrder(p.id)" @click="move(p.id, 1)">下移</Button>
            <a :href="p.home" target="_blank" rel="noreferrer" class="text-[11.5px] text-muted-foreground underline">官网</a>
            <!-- 行内配置（上游那页的「配置 ▾」）：凭据就挂在这家自己身上，不另开一处 -->
            <button
              v-if="hasConfigSection(p)"
              type="button"
              class="cursor-pointer rounded-md px-2 py-1 text-[11.5px] transition-colors"
              :class="openConfig.has(p.id)
                ? 'bg-primary/12 text-primary'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
              @click="toggleConfig(p.id)"
            >
              配置 {{ openConfig.has(p.id) ? '▴' : '▾' }}
            </button>
            <button
              v-if="p.implemented"
              type="button"
              role="switch"
              :aria-checked="inOrder(p.id)"
              :title="inOrder(p.id) ? '停用' : '启用'"
              class="relative h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors"
              :class="inOrder(p.id) ? 'bg-primary' : 'bg-muted'"
              @click="toggleSource(p.id)"
            >
              <span
                class="absolute top-0.5 h-4 w-4 rounded-full bg-card shadow-xs transition-[left]"
                :class="inOrder(p.id) ? 'left-[1.125rem]' : 'left-0.5'"
              />
            </button>
            <span v-else class="w-9 shrink-0 text-center text-[11px] text-muted-foreground">—</span>
          </div>

          <!--
            行内配置面板（第 57 期 E 段）：按注册表 `config_fields` 渲染 —— secret 走掩码输入、
            select 走下拉，于是「凭据」与「抓取参数」都挂在这一家自己身上（上游同款形态）。
            「测试」用当前输入值试一次、**不落盘**；只有「保存」才写配置。
          -->
          <div
            v-if="hasConfigSection(p) && openConfig.has(p.id)"
            class="border-t border-border/60 bg-muted/20 px-4 py-3"
          >
            <div
              v-if="p.needs_setup"
              class="mb-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-[11.5px] text-amber-700 dark:text-amber-400"
            >
              ⚠ 该来源需要一个密钥才能启用
            </div>
            <div v-for="f in p.config_fields" :key="f.key" class="mb-2.5 last:mb-0">
              <label class="mb-1 block text-[11px] text-muted-foreground">
                {{ f.label }}
                <span
                  v-if="f.type === 'secret'"
                  class="ml-1"
                  :class="p.has_config ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'"
                >
                  {{ p.has_config ? '已设置' : '未设置' }}
                </span>
              </label>
              <select
                v-if="f.type === 'select'"
                :value="fieldValue(p, f)"
                class="w-[220px] rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
                @change="setDraft(p.id, f.key, ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="o in f.options || []" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <input
                v-else
                :value="fieldValue(p, f)"
                type="password"
                :placeholder="p.has_config ? '已设置（留空 = 保持，输入新值可覆盖）' : (f.placeholder || '未设置')"
                class="w-[420px] max-w-full rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
                @input="setDraft(p.id, f.key, ($event.target as HTMLInputElement).value)"
              >
              <div v-if="f.hint" class="mt-1 text-[11px] text-muted-foreground">{{ f.hint }}</div>
            </div>
            <div v-if="p.config_hint" class="mb-2 text-[11px] text-muted-foreground">{{ p.config_hint }}</div>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" :disabled="rowIsBusy(p.id)" @click="testRow(p)">
                {{ rowIsBusy(p.id) ? '测试中…' : '测试' }}
              </Button>
              <Button size="sm" variant="primary" :disabled="rowIsBusy(p.id)" @click="saveRow(p)">保存</Button>
              <Button size="sm" variant="ghost" :disabled="rowIsBusy(p.id)" @click="clearRow(p)">重置</Button>
              <span class="text-[11px] text-muted-foreground">测试只按当前输入试一次，不保存任何设置</span>
            </div>
          </div>
        </div>
      </div>
      <div
        v-if="providersLoading && !providers.length"
        class="px-4 py-6 text-center text-[11.5px] text-muted-foreground"
      >
        加载中…
      </div>
      <div
        v-else-if="!filteredGroups.length"
        class="px-4 py-6 text-center text-[11.5px] text-muted-foreground"
      >
        {{ providers.length ? '没有匹配的提供商' : '提供商目录为空 —— 请点上方「重试」' }}
      </div>

    </Card>

    <!--
      真联网体检（第 59 期）：一次看清 14 家「谁能用、谁为什么不能用」。
      ⚠️ 会**真出网**（每家检索一次）；关键词留空时用**各家样本** ——
      地区性目录（Aladin / Lubimyczytac / RanobeDB）必须用当地书名，否则会把好家误报成「无结果」。
    -->
    <Card v-if="has('sources')" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">联网体检</span>
        <span class="text-[11.5px] text-muted-foreground">
          每家真检索一次，按「限流 / 拒绝 / 反爬拦截 / 能连通但解析不到」分门别类 ——
          「检测连通性」只说能不能用，这里说**该做什么**
        </span>
        <input
          v-model="healthQuery"
          type="text"
          placeholder="关键词（留空 = 用各家样本）"
          class="ml-auto h-7 w-[190px] rounded-md border border-border bg-muted px-2.5 text-[11.5px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
        <Button size="sm" :disabled="healthRunning" @click="runHealth">
          {{ healthRunning ? '体检中…（14 家约 1 分钟）' : '开始体检' }}
        </Button>
      </div>

      <div v-if="health?.ran_at" class="border-b border-border px-4 py-2 text-[11.5px] text-muted-foreground">
        可用 <span class="text-emerald-600 dark:text-emerald-400">{{ health.summary.usable ?? 0 }}</span>
        · 未填密钥 {{ health.summary.missing_key ?? 0 }}
        · 待处理 <span class="text-destructive">{{ health.summary.problems ?? 0 }}</span>
        · 耗时 {{ (health.elapsed_ms / 1000).toFixed(1) }}s
        · {{ health.samples ? '关键词：各家样本' : '关键词：' + health.query }}
        · 结果只存在内存里（后端重启即清空）
      </div>
      <div v-else class="px-4 py-2 text-[11.5px] text-muted-foreground">尚未体检过。</div>

      <table v-if="health?.ran_at" class="w-full text-[11.5px]">
        <thead>
          <tr class="border-b border-border text-left text-muted-foreground">
            <th class="px-3 py-2 font-medium">来源</th>
            <th class="px-3 py-2 font-medium">结论</th>
            <th class="px-3 py-2 font-medium">耗时</th>
            <th class="px-3 py-2 font-medium">条数</th>
            <th class="px-3 py-2 font-medium">首条结果 / 原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="sid in health.order" :key="sid" class="border-b border-border/60 last:border-b-0">
            <td class="px-3 py-1.5 text-foreground">
              {{ health.items[sid].label }}
              <span
                v-if="health.items[sid].fragile"
                class="ml-1 rounded-full bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >易失效</span>
            </td>
            <td class="px-3 py-1.5" :class="healthClass(health.items[sid].kind)">
              {{ health.kind_labels[health.items[sid].kind] || health.items[sid].kind }}
            </td>
            <td class="px-3 py-1.5 text-muted-foreground">{{ health.items[sid].ms }} ms</td>
            <td class="px-3 py-1.5 text-muted-foreground">{{ health.items[sid].count }}</td>
            <td class="px-3 py-1.5 text-muted-foreground">
              {{ health.items[sid].first || health.items[sid].error }}
            </td>
          </tr>
        </tbody>
      </table>
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

      <!-- 跨源字段级合并（第 58 期）：默认开，且只在「够格的候选来自 ≥2 家」时才真的合并 -->
      <div class="flex items-center gap-4 border-t border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">跨源字段级合并</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            同一本书在多家都有候选时<strong>逐字段择优</strong>（简介信 Google Books、年份/语言信 Open Library…），
            题材多源合并去重 —— 而不是「谁的匹配分最高就全用谁」。
            <span class="text-muted-foreground">
              只有与最佳候选足够接近（匹配分 ≥ 0.7 且 ≥ 最佳分的 90%）的候选才参与，
              避免把同名不同书的字段拼在一起；关掉即回到只用最佳候选。
            </span>
          </div>
        </div>
        <Button
          size="sm"
          :variant="mf.merge_sources === false ? 'primary' : 'ghost'"
          :disabled="saving"
          @click="setVal('metadata_fetch.merge_sources', mf.merge_sources === false); saveSection('metadata')"
        >
          {{ mf.merge_sources === false ? '开启' : '关闭' }}
        </Button>
      </div>
      <!-- 按语种自动重排（第 60 期）：只改顺序、不筛源；每档内保持你设的顺序 -->
      <div class="flex items-center gap-4 border-t border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">按书籍语种自动重排来源顺序</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            语种已知时，把<strong>专精该语种</strong>的家排到最前（韩 → Aladin、波 → Lubimyczytac、
            日 → RanobeDB），<strong>多语种通吃</strong>的居中（Google Books / Open Library / Kobo），
            专精别的语种的排最后 —— <span class="text-muted-foreground">每档内仍保持你上面设的顺序，
            且<strong>不会少问任何一家</strong>（只是先问相关的）。书的语种来自书目里的「语言」，
            没填就按原顺序检索。</span>
          </div>
        </div>
        <Button
          size="sm"
          :variant="mf.auto_order_by_language === false ? 'primary' : 'ghost'"
          :disabled="saving"
          @click="setVal('metadata_fetch.auto_order_by_language', mf.auto_order_by_language === false); saveSection('metadata')"
        >
          {{ mf.auto_order_by_language === false ? '开启' : '关闭' }}
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
                  <!-- 本次实际检索顺序（第 60 期）：只在被语种重排过时才显示，避免噪音 -->
                  <div
                    v-if="reordered(i)"
                    class="mt-0.5 text-[10.5px] text-muted-foreground"
                    :title="`按本书语种重排后的检索顺序：${(i.sources_order ?? []).join(' → ')}`"
                  >
                    按语种重排：{{ (i.sources_order ?? []).join(' → ') }}
                  </div>
                </template>
                <span v-else class="text-[11px] text-muted-foreground">
                  {{ i.skipped || i.error || '没有候选' }}
                </span>
              </td>
              <td class="px-3 py-2 align-top">
                <!-- 合并自 N 源（第 58 期）：说明这次的值不止来自一家、逐字段择优 -->
                <div
                  v-if="i.merged_from?.length"
                  class="mb-0.5 text-[10.5px] text-primary"
                  :title="`逐字段择优：${i.merged_from.join(' + ')}`"
                >
                  合并自 {{ i.merged_from.length }} 源（{{ i.merged_from.join(' + ') }}）
                </div>
                <div v-if="Object.keys(i.changes).length" class="text-[11.5px]">
                  <div v-for="(v, k) in i.changes" :key="k" class="text-muted-foreground">
                    <span class="text-foreground">{{ fieldZh(k) }}</span>：
                    {{ short((v as any).to) }}
                    <!-- 每个字段各自标来源：合并后「简介来自 Google Books、年份来自 Open Library」要看得见 -->
                    <span v-if="(v as any).source" class="text-[10.5px] opacity-70">
                      · {{ (v as any).source }}
                    </span>
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
        '按书的语种翻译 / 本地化检索词（当前只按语种重排来源顺序，不做跨语言检索）',
        '自定义来源权重（当前固定三档：专精本语种 → 多语种通吃 → 专精别的语种，档内保持你设的顺序）',
      ]"
      note="已实现：14 家提供商全部接入（Open Library / Google Books / iTunes / AudNexus / RanobeDB 免密钥即用；Hardcover / Comic Vine / Aladin 填密钥即用；Amazon / Goodreads / Kobo / Audible / Libro.fm / Lubimyczytac 为页面抓取型、站点改版可能失效）、联网体检（逐家分门别类：限流 / 拒绝 / 反爬拦截 / 能连通但解析不到）、源选择与顺序、按书籍语种自动重排来源顺序（专精本语种 → 多语种通吃 → 专精别语种，档内保持你的顺序且不筛掉任何一家）、连通性自检、按注册表渲染的密钥与参数配置、入库自动抓取、ISBN 精确匹配、跨源字段级合并（逐字段择优 + 题材合并，仅够格候选参与）、字段级写入策略、字段级锁定（单本书逐字段 / 封面，只挡抓取）、置信度阈值、题材黑名单、自定义字段（定义管理 + 按书的值 + 抓取补默认值）、「先预览再应用」的手动抓取面板（逐本显示本次实际检索顺序），以及作者传记 / 头像抓取与本地覆盖编辑。"
    />
  </div>
</template>
