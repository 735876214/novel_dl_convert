<script setup lang="ts">
/**
 * 书源工具（第 86 期能力的接线页）：**导入 / 台账 / 登录 / 验证**。
 *
 * 这一页此前只存在于后端（16 条接口 + 契约测试），界面上完全没有入口 —— 本期补上。
 * 四块：
 *
 * ① **导入**：粘贴 Legado 书源原文（或本项目导出文件）→ **默认 dry-run** 出差异表，
 *    逐条给结论（新 / 更新 / 重复 / 撞名 / 不可执行）；撞名与更新要用户**逐条选**
 *    怎么处理（跳过 / 覆盖 / 两条并存），**绝不静默覆盖**。确认后才真正落盘，
 *    而覆盖前后端已把旧规则原文存进历史（可回滚）。
 * ② **台账**：全部书源的启停、能力档位、分组、最近验证；可重分析、看覆盖历史并回滚、导出。
 * ③ **登录**：Cookie（**只回有没有，不回值**）+ 书源变量（同样是「设没设」）+ 登录声明。
 * ④ **验证**：单源 / 全部源的连通性探测（后端零外呼之外的实探，逐条回报）。
 *
 * ⚠️ 凭据一律**不回显**：后端只回 `has_*`，界面上不给「查看已保存的值」这种按钮 ——
 * 那是把凭据明文搬到屏幕上，与后端刻意的口径相悖（填了就能用，忘了就重填）。
 */
import { computed, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  api,
  type SourceCookieStatus,
  type SourceImportResult,
  type SourceImportRow,
  type SourceLedgerRow,
  type SourceLoginSpec,
  type SourceVarsResult,
} from '@/lib/api'
import { importSummary } from '@/lib/sourceImport'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

/** 错误 → 可读文案（本页只做展示，不需要后端给的完整诊断串） */
function msg(e: unknown): string {
  return e instanceof Error ? e.message : '操作失败'
}

// ---------------- ⓪ 追更（增强 E）----------------
// 追更**默认开启**且会周期性出网 ⇒ 必须能一眼看到状态并一键停掉。
// 开关与三个数值都走 `api.saveConfig({auto_update: …})`（三处登记已完成），
// 状态与「立即跑一轮」走专门的只读/触发接口。
type AutoState = { running: boolean; enabled: boolean; interval_hours: number }
const autoState = ref<AutoState | null>(null)
const autoForm = ref({ interval_hours: 12, max_books: 50, request_delay: 3 })
const autoBusy = ref('')

async function loadAuto(): Promise<void> {
  try {
    autoState.value = await api.autoupdateState()
    const cfg = await api.getConfig()
    const a = (cfg as unknown as {
      config?: { auto_update?: Partial<typeof autoForm.value> }
    }).config?.auto_update
    if (a) autoForm.value = { ...autoForm.value, ...a }
  } catch (e) {
    ui.toast(msg(e))
  }
}

async function saveAuto(patch: Partial<AutoState & typeof autoForm.value>): Promise<void> {
  autoBusy.value = 'save'
  try {
    // 整段提交（数值 + 开关），后端按 EDITABLE 白名单收下并**热应用**
    // （关掉即停线程，不是只停止下一轮外呼）
    await api.saveConfig({ auto_update: { ...autoForm.value, ...patch } })
    ui.toast('追更设置已保存并即时生效')
    await loadAuto()
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    autoBusy.value = ''
  }
}

async function runAuto(): Promise<void> {
  autoBusy.value = 'run'
  try {
    const r = await api.autoupdateRun()
    // ⚠️ `added === 0` 有**两种**完全不同的原因（第 93 期）：源上没有新章，或者
    // 闸门没过、一本都没跑。后端把后者放在 `blocked` 里且 `skipped` 等于 `total` ——
    // 一句「新增 0 章」会把「你关着开关」说成「源站没更新」，那条提示比不提示更坏。
    ui.toast(r.blocked
      ? `追更未执行：${r.blocked}`          // 闸门原文来自服务端，界面不另写一句
      : r.total
        ? `追更完成：检查 ${r.total} 本，新增 ${r.added} 章`
          + (r.errors ? `，失败 ${r.errors} 本（见活动日志）` : '')
        : '没有可追更的书（只追有留档的下载书）')
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    autoBusy.value = ''
  }
}

void loadAuto()

// ---------------- ① 导入 ----------------
const paste = ref('')
const origin = ref('paste')
const preview = ref<SourceImportResult | null>(null)
const resolutions = ref<Record<string, string>>({})
const importing = ref(false)
//: 展开「字段明细」的那一行（第 94 期阶段 5）。空串 = 都收起。
//: 收起是默认：一屏里几十行源、每行十几项字段，全展开等于什么都没说。
const reportFor = ref('')

const rows = computed<SourceImportRow[]>(() => preview.value?.rows ?? [])

/** 「字段明细」里每种状态的说法。三档与后端的 `status` 逐字对应，前端不自己判。 */
const FIELD_STATUS_LABEL: Record<string, string> = {
  executable: '直接用',
  ported: '换了个形态',
  unsupported: '本项目没有',
}

/** 只列「本项目没有」的那些 —— 用户要的是「我源里的东西丢在哪儿了」。 */
function lostFields(r: SourceImportRow) {
  return r.field_report.filter((f) => f.status === 'unsupported')
}

function verdictLabel(v: string): string {
  return (
    {
      new: '新增',
      update: '更新',
      duplicate: '内容相同',
      conflict: '撞名 / 同站点',
      unsupported: '不可执行',
    }[v] || v
  )
}

function verdictTone(v: string): 'accent' | undefined {
  return v === 'conflict' || v === 'unsupported' ? 'accent' : undefined
}

async function previewImport(): Promise<void> {
  if (!paste.value.trim()) {
    ui.toast('先粘贴书源 JSON（或导出文件内容）')
    return
  }
  try {
    const res = await api.sourcesImport({
      payload: paste.value,
      origin: origin.value || 'paste',
      dry_run: true,
    })
    preview.value = res
    // 需要用户拍板的条目默认最保守：**跳过**（覆盖是破坏性动作，不该是默认值）
    const next: Record<string, string> = {}
    for (const r of res.rows ?? []) {
      if (r.verdict === 'conflict' || r.verdict === 'update') next[r.name] = 'skip'
    }
    resolutions.value = next
  } catch (e) {
    preview.value = null
    ui.toast(msg(e))
  }
}

async function applyImport(): Promise<void> {
  importing.value = true
  try {
    const res = await api.sourcesImport({
      payload: paste.value,
      origin: origin.value || 'paste',
      dry_run: false,
      resolutions: resolutions.value,
    })
    // 逐档计数 → 人话的这一份**只有** `lib/sourceImport.ts`（第 94 期：本页与
    // 「书源管理 → 导入书源」卡共用，别再在这里手写第二串）
    ui.toast(importSummary(res.counts))
    for (const it of (res.items ?? []).filter((i) => !i.ok).slice(0, 3)) {
      ui.toast(`${it.name}：${it.note || '失败'}`)
    }
    preview.value = null
    paste.value = ''
    await loadLedger()
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    importing.value = false
  }
}

async function exportAll(): Promise<void> {
  try {
    const data = await api.sourcesExport()
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    ui.toast('已导出到剪贴板（导出后再导入是幂等的）')
  } catch (e) {
    ui.toast(msg(e))
  }
}

// ---------------- ② 台账 ----------------
const ledger = ref<SourceLedgerRow[]>([])
const loading = ref(false)
const busy = ref('')
const historyFor = ref('')
const history = ref<Array<{ id: string; note: string; created_at: number }>>([])

async function loadLedger(): Promise<void> {
  loading.value = true
  try {
    ledger.value = (await api.sourcesLedger()).items
  } catch (e) {
    ui.toast(msg(e))
    ledger.value = []
  } finally {
    loading.value = false
  }
}

async function toggle(row: SourceLedgerRow): Promise<void> {
  busy.value = row.name
  try {
    await api.sourceEnabled(row.name, !row.enabled)
    await loadLedger()
  } catch (e) {
    // 内置源会被后端如实拒绝（没有可挂启停状态的规则文件）—— 把原因原样告诉用户
    ui.toast(msg(e))
  } finally {
    busy.value = ''
  }
}

async function reanalyze(row: SourceLedgerRow): Promise<void> {
  busy.value = row.name
  try {
    const res = await api.sourceReanalyze(row.name)
    ui.toast(`${row.name}：档位 ${res.supported}${res.usable ? '，现在能跑了' : ''}`)
    await loadLedger()
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    busy.value = ''
  }
}

async function openHistory(name: string): Promise<void> {
  if (historyFor.value === name) {
    historyFor.value = ''
    return
  }
  historyFor.value = name
  history.value = []
  try {
    history.value = (await api.sourceHistory(name)).items
  } catch (e) {
    ui.toast(msg(e))
  }
}

async function rollback(name: string, id: string): Promise<void> {
  busy.value = name
  try {
    await api.sourceRollback(name, id)
    ui.toast(`${name} 已回滚到选中的那一版`)
    await loadLedger()
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    busy.value = ''
  }
}

// ---------------- ③ 登录 ----------------
const loginFor = ref('')
const spec = ref<SourceLoginSpec | null>(null)
const cookieText = ref('')
const cookieDomains = ref('')
const varsState = ref<SourceVarsResult | null>(null)
const varValues = ref<Record<string, string>>({})

/** 需要填的变量键 = 规则引用到的 ∪ 已设置过的（后者让用户能改动之前填的键名） */
const varKeys = computed(() => {
  const s = new Set<string>([...(varsState.value?.referenced ?? [])])
  for (const k of Object.keys(varsState.value?.keys ?? {})) s.add(k)
  return [...s]
})

async function openLogin(name: string): Promise<void> {
  if (loginFor.value === name) {
    loginFor.value = ''
    return
  }
  loginFor.value = name
  spec.value = null
  varValues.value = {}
  try {
    const [s, v] = await Promise.all([api.sourceLoginSpec(name), api.sourceVars(name)])
    spec.value = s
    varsState.value = v
  } catch (e) {
    ui.toast(msg(e))
  }
}

async function saveCookie(): Promise<void> {
  if (!loginFor.value || !cookieText.value.trim()) {
    ui.toast('先粘贴 Cookie')
    return
  }
  try {
    const domains = cookieDomains.value
      .split(',')
      .map((d) => d.trim())
      .filter(Boolean)
    const st = await api.sourceCookieSave(loginFor.value, cookieText.value, domains)
    spec.value = spec.value ? { ...spec.value, cookie: st } : spec.value
    cookieText.value = ''
    ui.toast('登录态已保存（值不会被回显）')
  } catch (e) {
    ui.toast(msg(e))
  }
}

async function clearCookie(): Promise<void> {
  if (!loginFor.value) return
  try {
    const res = await api.sourceCookieClear(loginFor.value)
    ui.toast(res.cleared ? '已清除登录态' : '本来就没有登录态')
    const st: SourceCookieStatus = await api.sourceCookie(loginFor.value)
    spec.value = spec.value ? { ...spec.value, cookie: st } : spec.value
  } catch (e) {
    ui.toast(msg(e))
  }
}

async function saveVars(): Promise<void> {
  if (!loginFor.value) return
  try {
    varsState.value = await api.sourceVarsSave(loginFor.value, varValues.value)
    varValues.value = {}
    ui.toast('变量已保存（值不会被回显；留空即清除该键）')
  } catch (e) {
    ui.toast(msg(e))
  }
}

// ---------------- ④ 验证 ----------------
const probing = ref(false)
const probeResult = ref('')

async function probeAll(): Promise<void> {
  probing.value = true
  try {
    probeResult.value = JSON.stringify(await api.sourcesProbeAll(), null, 2)
    ui.toast('验证完成，结果见下方')
    await loadLedger()
  } catch (e) {
    ui.toast(msg(e))
  } finally {
    probing.value = false
  }
}

void loadLedger()
</script>

<template>
  <div class="flex flex-col gap-4 p-4">
    <!-- ⓪ 追更（增强 E）：默认开启且会出网 ⇒ 状态必须一眼可见，且能一键停掉 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <!-- ⚠️ 窄屏（第 87 期 F 实测 360px）下侧栏不折叠、内容区只剩百来像素：
             少了 `shrink-0 whitespace-nowrap`，这个标题会被压成**一字一行的竖排**。
             宁可让它整块换行（外层是 flex-wrap），也不要压扁文字。 -->
        <span class="shrink-0 text-[13px] font-medium whitespace-nowrap text-foreground">自动追更</span>
        <Badge :tone="autoState?.enabled === false ? 'warn' : autoState?.running ? 'ok' : 'neutral'">
          {{ autoState?.enabled === false ? '已暂停' : autoState?.running ? '运行中' : '未运行' }}
        </Badge>
        <span class="text-[11.5px] text-muted-foreground">
          每 {{ autoForm.interval_hours }} 小时检查一次已下载的书，只追加新章
        </span>
        <Button
          size="sm"
          class="ml-auto"
          :disabled="!!autoBusy"
          @click="saveAuto({ enabled: autoState?.enabled === false })"
        >
          {{ autoState?.enabled === false ? '启用追更' : '暂停追更' }}
        </Button>
        <Button size="sm" :disabled="!!autoBusy" @click="runAuto">
          {{ autoBusy === 'run' ? '追更中…' : '立即追更一轮' }}
        </Button>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
        <label class="flex items-center gap-1">
          间隔（小时）
          <input
            v-model.number="autoForm.interval_hours"
            type="number"
            min="1"
            class="w-20 rounded-md border border-border bg-muted px-2 py-1 text-foreground outline-none focus:border-ring"
          >
        </label>
        <label class="flex items-center gap-1">
          单轮上限（本）
          <input
            v-model.number="autoForm.max_books"
            type="number"
            min="1"
            class="w-20 rounded-md border border-border bg-muted px-2 py-1 text-foreground outline-none focus:border-ring"
          >
        </label>
        <label class="flex items-center gap-1">
          每本间隔（秒）
          <input
            v-model.number="autoForm.request_delay"
            type="number"
            min="0"
            class="w-20 rounded-md border border-border bg-muted px-2 py-1 text-foreground outline-none focus:border-ring"
          >
        </label>
        <Button size="sm" :disabled="!!autoBusy" @click="saveAuto({})">保存设置</Button>
      </div>
      <div class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
        首轮不会在服务启动时立刻跑（等一个间隔）；想立刻追一次就点上面的按钮。
      </div>
    </Card>

    <!-- ① 导入 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">导入书源</span>
        <Badge>默认只预览，不落盘</Badge>
        <Button size="sm" class="ml-auto" :disabled="importing" @click="previewImport">
          预览（不写入）
        </Button>
        <Button size="sm" :disabled="importing || !preview" @click="applyImport">
          {{ importing ? '导入中…' : '确认导入' }}
        </Button>
      </div>
      <div class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
        粘贴 Legado 书源原文（单个 / 数组 / JSONL）或本项目导出的文件内容。
        预览会逐条给出结论：新增 / 更新 / 内容相同 / 撞名 / 不可执行。
      </div>
      <textarea
        v-model="paste"
        rows="6"
        placeholder='[{"bookSourceName": "...", "bookSourceUrl": "..."}]'
        class="mt-2 w-full rounded-md border border-border bg-transparent px-2 py-1.5 font-mono text-[11.5px] text-foreground outline-none focus:border-primary"
      />
      <div class="mt-2 flex flex-wrap items-center gap-2 text-[11.5px]">
        <span class="text-muted-foreground">来源标记</span>
        <input
          v-model="origin"
          class="w-40 rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
        />
        <Button size="sm" class="ml-auto" @click="exportAll">导出全部用户源</Button>
      </div>

      <div v-if="rows.length" class="mt-3 border-t border-border pt-2">
        <div
          v-for="r in rows"
          :key="r.name"
          class="flex flex-wrap items-center gap-2 border-b border-border/60 py-1.5 text-[11.5px] last:border-b-0"
        >
          <Badge :tone="verdictTone(r.verdict)">{{ verdictLabel(r.verdict) }}</Badge>
          <code class="min-w-0 flex-1 truncate text-foreground" :title="r.name">{{ r.name }}</code>
          <span v-if="r.conflict_with" class="shrink-0 text-muted-foreground">
            撞上 {{ r.conflict_with }}
          </span>
          <span v-if="r.changed_fields.length" class="shrink-0 text-muted-foreground">
            变化：{{ r.changed_fields.slice(0, 3).join('、') }}
          </span>
          <span v-if="r.supported !== 'yes'" class="shrink-0 text-muted-foreground">
            {{ r.supported === 'no' ? '不可执行（只记台账）' : '部分支持' }}
          </span>
          <select
            v-if="r.verdict === 'conflict' || r.verdict === 'update'"
            v-model="resolutions[r.name]"
            class="shrink-0 rounded-md border border-border bg-transparent px-1.5 py-0.5 text-[11.5px] text-foreground outline-none focus:border-primary"
          >
            <option value="skip">跳过</option>
            <option value="overwrite">覆盖（先备份旧规则）</option>
            <option value="keep_both">两条并存</option>
          </select>
          <!-- 第 94 期阶段 5：这条源里**每一个**字段的去向（含被丢掉的那些）。
               没有它，用户源里的「详情页规则」在导入后凭空消失，界面上一句话都没有。 -->
          <Button
            v-if="r.field_report.length"
            size="sm"
            class="shrink-0"
            @click="reportFor = reportFor === r.name ? '' : r.name"
          >
            {{ reportFor === r.name ? '收起明细' : `字段明细 ${r.field_report.length}` }}
          </Button>
        </div>
        <div v-for="r in rows" :key="`note-${r.name}`" class="text-[11px] text-muted-foreground">
          <span v-for="(n, i) in r.notes" :key="i">{{ r.name }}：{{ n }}</span>
        </div>
        <div v-for="r in rows" :key="`report-${r.name}`">
          <div
            v-if="reportFor === r.name"
            class="mb-2 mt-1.5 rounded-md border border-border bg-muted/40 px-3 py-2 text-[11.5px]"
          >
            <div class="mb-1 font-medium text-foreground">
              {{ r.display_name || r.name }}：这条源里 {{ r.field_report.length }} 个字段的去向
              <span class="font-normal text-muted-foreground">
                （本项目没有 {{ lostFields(r).length }} 项）
              </span>
            </div>
            <div
              v-for="f in r.field_report"
              :key="f.field"
              class="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b border-border/40 py-1 last:border-b-0"
            >
              <code class="shrink-0 text-foreground">{{ f.field }}</code>
              <Badge :tone="f.status === 'unsupported' ? 'warn' : undefined" class="shrink-0">
                {{ FIELD_STATUS_LABEL[f.status] || f.status }}
              </Badge>
              <span v-if="f.why" class="min-w-0 flex-1 text-muted-foreground">{{ f.why }}</span>
              <span v-if="f.instead" class="w-full text-muted-foreground">→ {{ f.instead }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else-if="preview" class="mt-2 text-[11.5px] text-muted-foreground">
        这份内容里没有可导入的书源。
      </div>
    </Card>

    <!-- ② 台账 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">书源台账</span>
        <Badge>{{ ledger.length }} 个</Badge>
        <span class="text-[11.5px] text-muted-foreground">
          启停不动文件；停用只是不注册，随时能再打开
        </span>
        <Button size="sm" class="ml-auto" :disabled="loading" @click="loadLedger">刷新</Button>
      </div>

      <div v-if="loading && !ledger.length" class="mt-2 text-[12.5px] text-muted-foreground">
        读取中…
      </div>
      <div v-else-if="!ledger.length" class="mt-2 text-[12.5px] text-muted-foreground">
        台账里还没有记录（手写 / 内置源不写台账，属正常）。
      </div>
      <div v-else class="mt-2">
        <div
          v-for="row in ledger"
          :key="row.name"
          class="border-b border-border/60 py-2 text-[11.5px] last:border-b-0"
        >
          <div class="flex flex-wrap items-center gap-2">
            <code class="min-w-0 flex-1 truncate text-foreground" :title="row.name">
              {{ row.name }}
            </code>
            <Badge v-if="row.imported">导入</Badge>
            <Badge v-if="row.group_name">{{ row.group_name }}</Badge>
            <Badge :tone="row.supported === 'yes' ? undefined : 'accent'">
              {{ row.supported === 'yes' ? '可用' : row.supported === 'no' ? '不可执行' : '部分支持' }}
            </Badge>
            <span v-if="row.verified_at" class="shrink-0 text-muted-foreground">
              验证 {{ row.verify_ok ? '通过' : '未通过' }} · {{ row.verify_ms }}ms
            </span>
            <Button size="sm" :disabled="busy === row.name" @click="toggle(row)">
              {{ row.enabled ? '停用' : '启用' }}
            </Button>
            <Button size="sm" :disabled="busy === row.name" @click="reanalyze(row)">重分析</Button>
            <Button size="sm" @click="openHistory(row.name)">
              {{ historyFor === row.name ? '收起历史' : '历史' }}
            </Button>
          </div>
          <div v-if="row.verify_error" class="mt-1 text-muted-foreground">
            验证失败：{{ row.verify_error }}
          </div>
          <div v-if="row.last_update_note" class="mt-1 text-muted-foreground">
            追更：{{ row.last_update_note }}
          </div>
          <div v-for="u in row.unsupported" :key="`${row.name}-${u.field}`" class="mt-1 text-muted-foreground">
            不支持 {{ u.field }}：{{ u.why }}<span v-if="u.instead">（改用 {{ u.instead }}）</span>
          </div>
          <div v-if="historyFor === row.name" class="mt-2 pl-4">
            <div v-if="!history.length" class="text-muted-foreground">没有覆盖历史。</div>
            <div
              v-for="h in history"
              :key="h.id"
              class="flex flex-wrap items-center gap-2 border-l border-border py-1 pl-2"
            >
              <span class="text-muted-foreground">{{ h.note || '覆盖前备份' }}</span>
              <Button size="sm" :disabled="busy === row.name" @click="rollback(row.name, h.id)">
                回滚到此
              </Button>
            </div>
          </div>
        </div>
      </div>
    </Card>

    <!-- ③ 登录 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">登录与凭据</span>
        <Badge>值不会回显</Badge>
        <select
          v-model="loginFor"
          class="ml-auto rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
          @change="openLogin(loginFor)"
        >
          <option value="">选择一个书源…</option>
          <option v-for="row in ledger" :key="`login-${row.name}`" :value="row.name">
            {{ row.name }}
          </option>
        </select>
      </div>

      <div v-if="spec" class="mt-2 text-[11.5px]">
        <div class="text-muted-foreground">
          登录态：{{ spec.cookie?.has ? `已保存 ${spec.cookie?.count ?? 0} 条` : '未保存' }}
          <span v-if="spec.cookie?.names?.length">
            （{{ spec.cookie.names.slice(0, 5).join('、') }}）
          </span>
        </div>
        <div v-if="spec.open_url" class="mt-1 text-muted-foreground">
          登录页：<a class="underline" :href="spec.open_url" target="_blank" rel="noreferrer">{{ spec.open_url }}</a>
        </div>
        <div v-if="spec.instructions" class="mt-1 text-muted-foreground">{{ spec.instructions }}</div>
        <div v-if="spec.note" class="mt-1 text-muted-foreground">{{ spec.note }}</div>
        <div v-if="spec.unsupported.length" class="mt-1 text-muted-foreground">
          这个源有 {{ spec.unsupported.length }} 个步骤本工具做不到，规则里已如实标注。
        </div>

        <textarea
          v-model="cookieText"
          rows="3"
          placeholder="粘贴 Cookie（从浏览器开发者工具复制即可）"
          class="mt-2 w-full rounded-md border border-border bg-transparent px-2 py-1.5 font-mono text-[11.5px] text-foreground outline-none focus:border-primary"
        />
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <input
            v-model="cookieDomains"
            placeholder="补域（可选，逗号分隔；留空用书源声明的域）"
            class="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
          />
          <Button size="sm" @click="saveCookie">保存 Cookie</Button>
          <Button size="sm" @click="clearCookie">清除</Button>
        </div>

        <div v-if="varKeys.length" class="mt-3">
          <div class="text-muted-foreground">
            变量（规则里引用了 {{ varKeys.length }} 个；留空即清除）
          </div>
          <div v-for="k in varKeys" :key="`v-${k}`" class="mt-1 flex flex-wrap items-center gap-2">
            <code class="w-40 shrink-0 truncate text-foreground" :title="k">{{ k }}</code>
            <Badge v-if="varsState?.keys?.[k]">已设置</Badge>
            <input
              v-model="varValues[k]"
              type="password"
              :placeholder="varsState?.keys?.[k] ? '已设置（留空不改）' : '未设置'"
              class="min-w-0 flex-1 rounded-md border border-border bg-transparent px-2 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
            />
          </div>
          <Button size="sm" class="mt-2" @click="saveVars">保存变量</Button>
        </div>
      </div>
      <div v-else class="mt-2 text-[11.5px] text-muted-foreground">
        选一个书源就能看到它的登录声明、Cookie 状态与变量清单。
      </div>
    </Card>

    <!-- ④ 验证 -->
    <Card>
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">连通性验证</span>
        <span class="text-[11.5px] text-muted-foreground">逐个源实探一次，结果写入台账</span>
        <Button size="sm" class="ml-auto" :disabled="probing" @click="probeAll">
          {{ probing ? '验证中…' : '全部验证' }}
        </Button>
      </div>
      <pre
        v-if="probeResult"
        class="mt-2 max-h-72 overflow-auto rounded-md border border-border p-2 font-mono text-[11px] text-muted-foreground"
        >{{ probeResult }}</pre
      >
    </Card>
  </div>
</template>
