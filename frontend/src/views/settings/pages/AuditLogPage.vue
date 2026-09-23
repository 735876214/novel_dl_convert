<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type LogItem, type LogStorage } from '@/lib/api'

/**
 * SERVER → Audit Log（`/settings/admin/audit-log`）
 *
 * 真实现：直接读活动日志（`GET /api/logs`），把「谁做的」显示出来。
 * 「操作者」来自后端新增的 `actor` 字段（由鉴权中间件注入，见 `core/activity_log.py`）。
 *
 * 与上游的差异：上游是独立的审计子系统（操作者 / 类别 / Details / 筛选器齐全）；
 * 本项目复用活动日志，**类别由动作归并**（第 52 期起另有一套简单的留存策略：按大小轮转、
 * 保留 N 份、可选压缩，默认关闭 —— 关着就是原来的单文件追加）。
 * 历史条目没有 actor 字段 —— 一律按「未记录」渲染，不报错、不臆测。
 * 筛选支持动作 / 结果 / 操作者 / 关键字四维；操作者候选由后端从日志里**实际出现过的
 * 名字**汇总（`/api/logs` 的 `actors`），不受当前筛选影响，故选中后仍能切回来。
 */

const items = ref<LogItem[]>([])
const loading = ref(true)
const err = ref('')

const fAction = ref('')
const fStatus = ref('')
const fQ = ref('')
const fActor = ref('')
/** 操作者下拉的候选（后端另行取全量，**不受当前筛选影响** —— 否则选中一个就切不回来） */
const actors = ref<string[]>([])

/**
 * 类别筛选：**客户端**筛选（后端只接受单个 `action`，而类别是多动作集合）。
 * 作用范围是「当前已加载的条目」，UI 上如实标注。
 */
const fCategory = ref('')
/** 仅看「未记录操作者」的条目（历史条目 actor 为空，按名字筛不到它们） */
const onlyNoActor = ref(false)

/** 每档条数：后端只有 limit、没有 offset，故「加载更多」= 抬高 limit 重取 */
const LOAD_STEPS = [200, 500, 1000, 2000]
const stepIdx = ref(0)
const limit = computed(() => LOAD_STEPS[stepIdx.value])
const canLoadMore = computed(() => stepIdx.value < LOAD_STEPS.length - 1)

// ---- 留存策略（第 52 期）----
// 走既有 config / settings.json 覆盖层（与「高级」页同一份，随备份一起走），不另起存储。
// 默认**关闭** = 原来的「单文件一直追加」；开启后按大小轮转，读取端自动跨归档。
const { loadConfig, saveSection, saving, val, setVal } = useSettingsConfig()
/** 存盘情况：后端随日志一起返回（当前字节数 / 归档份数 / 生效策略） */
const storage = ref<LogStorage | null>(null)

const retEnabled = computed(() => Boolean(val('logging.retention.enabled')))
const retMaxMb = computed(() =>
  Math.max(1, Math.round(Number(val('logging.retention.max_bytes') || 5242880) / 1048576)),
)
const retKeep = computed(() => Math.max(1, Number(val('logging.retention.keep') || 5)))
const retCompress = computed(() => Boolean(val('logging.retention.compress')))

function setRet(key: string, v: unknown): void {
  setVal(`logging.retention.${key}`, v)
}

function fmtBytes(n: number): string {
  const v = Number(n) || 0
  if (v < 1024) return `${v} B`
  if (v < 1048576) return `${(v / 1024).toFixed(1)} KB`
  return `${(v / 1048576).toFixed(1)} MB`
}

async function saveRetention(): Promise<void> {
  await saveSection('logs')
  void load() // 存盘情况随日志一起返回，保存后重取以刷新显示
}

const ACTIONS = ['转换', '添加', '跳过', '重命名', '清理', '刮削']
const STATUSES = ['成功', '失败']

/** 类别由动作归并（上游有独立类别体系，本项目没有） */
const CATEGORY: Record<string, string> = {
  转换: '内容生成',
  添加: '内容生成',
  重命名: '文件变更',
  清理: '清理',
  跳过: '跳过',
}

function categoryOf(action: unknown): string {
  const a = String(action ?? '')
  return CATEGORY[a] ?? '其它'
}

async function load(): Promise<void> {
  loading.value = true
  err.value = ''
  try {
    const r = await api.logs({
      limit: limit.value,
      action: fAction.value || undefined,
      status: fStatus.value || undefined,
      q: fQ.value.trim() || undefined,
      actor: fActor.value || undefined,
    })
    items.value = r.items
    actors.value = r.actors ?? []
    storage.value = r.storage ?? null
  } catch (e) {
    err.value = e instanceof Error ? e.message : '读取失败'
    items.value = []
  } finally {
    loading.value = false
  }
}

function resetFilters(): void {
  fAction.value = ''
  fStatus.value = ''
  fQ.value = ''
  fActor.value = ''
  fCategory.value = ''
  onlyNoActor.value = false
  void load()
}

onMounted(async () => {
  // 留存策略取自服务端配置草稿；silent=true —— 配置拉不到不该在审计页弹「配置加载失败」，
  // 那会让人误以为日志也坏了（列表走独立的 load()）。
  await loadConfig(false, true)
  await load()
})

const okCount = computed(() => items.value.filter((i) => String(i.status) === '成功').length)
const failCount = computed(() => items.value.filter((i) => String(i.status) === '失败').length)
/** actor 为空的条数：历史条目（字段缺失）或未鉴权路径写入 */
const noActor = computed(
  () => items.value.filter((i) => !String(i.actor ?? '').trim()).length,
)

/** 类别筛选可选项（顺序固定，配合上方 CATEGORY 归并） */
const CATEGORIES = ['内容生成', '文件变更', '清理', '跳过', '其它']

/** 类别分布：按**已加载**条目统计，与 chips 上的数字一致 */
const categoryCounts = computed<Record<string, number>>(() => {
  const m: Record<string, number> = {}
  for (const i of items.value) {
    const c = categoryOf(i.action)
    m[c] = (m[c] ?? 0) + 1
  }
  return m
})

/**
 * 客户端筛选后的可见条目（类别 + 仅未记录）。
 * ⚠️ 与上方「动作 / 结果 / 操作者 / 关键字」不同 —— 那四维是**服务端**筛选，
 * 这两维后端不支持，故只作用于当前已加载的 N 条（UI 上已标注作用范围）。
 */
const visible = computed(() =>
  items.value.filter(
    (i) =>
      (!fCategory.value || categoryOf(i.action) === fCategory.value) &&
      (!onlyNoActor.value || !String(i.actor ?? '').trim()),
  ),
)

function loadMore(): void {
  if (!canLoadMore.value) return
  stepIdx.value += 1
  void load()
}

/** 导出**当前筛选结果**为 CSV（BOM 保中文；与既有「下载 activity.log」并列，后者是原始日志文件） */
function exportCsv(): void {
  const esc = (v: unknown): string => {
    const s = v === undefined || v === null ? '' : String(v)
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const head = ['时间', '操作者', '类别', '动作', '结果', '文件', '输出', '详情']
  const body = visible.value.map((i) =>
    [
      str(i, 'ts'),
      actorOf(i),
      categoryOf(i.action),
      str(i, 'action'),
      str(i, 'status'),
      str(i, 'file'),
      str(i, 'output'),
      str(i, 'detail'),
    ]
      .map(esc)
      .join(','),
  )
  const csv = `\uFEFF${[head.join(','), ...body].join('\r\n')}`
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `audit-${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function str(i: LogItem, k: string): string {
  const v = i[k]
  return v === undefined || v === null ? '' : String(v)
}

/** 操作者：缺失时显示「未记录」并弱化 —— 不假装知道是谁做的 */
function actorOf(i: LogItem): string {
  return str(i, 'actor').trim() || '未记录'
}

function downloadLog(): void {
  const a = document.createElement('a')
  a.href = api.logsDownloadUrl()
  a.download = 'activity.log'
  a.click()
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">审计日志</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Audit Log</span>
      <span class="text-[11.5px] text-muted-foreground">
        已加载 {{ items.length }} 条 · 成功 {{ okCount }} · 失败 {{ failCount }}
        <span v-if="visible.length !== items.length"> · 当前筛出 {{ visible.length }} 条</span>
      </span>
      <Button size="sm" class="ml-auto" :disabled="loading" @click="load">刷新</Button>
      <Button size="sm" :disabled="!visible.length" @click="exportCsv">导出当前筛选 CSV</Button>
      <Button size="sm" @click="downloadLog">下载 activity.log</Button>
    </div>

    <!-- 筛选 -->
    <Card class="mb-4">
      <div class="flex flex-wrap items-center gap-2">
        <select
          v-model="fAction"
          aria-label="按动作筛选"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
          @change="load"
        >
          <option value="">全部动作</option>
          <option v-for="a in ACTIONS" :key="a" :value="a">{{ a }}</option>
        </select>
        <select
          v-model="fStatus"
          aria-label="按结果筛选"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
          @change="load"
        >
          <option value="">全部结果</option>
          <option v-for="s in STATUSES" :key="s" :value="s">{{ s }}</option>
        </select>
        <select
          v-model="fActor"
          aria-label="按操作者筛选"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
          @change="load"
        >
          <option value="">全部操作者</option>
          <option v-for="a in actors" :key="a" :value="a">{{ a }}</option>
        </select>
        <input
          v-model="fQ"
          type="text"
          placeholder="搜索文件名 / 输出 / 详情…"
          aria-label="关键字"
          class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          @keydown.enter="load"
        >
        <Button :disabled="loading" @click="load">查询</Button>
        <Button variant="ghost" @click="resetFilters">重置</Button>
      </div>

      <!-- 客户端筛选（后端不支持这两维）：作用范围 = 当前已加载的条目，如实标注 -->
      <div class="mt-2.5 flex flex-wrap items-center gap-1.5 border-t border-border pt-2.5">
        <span class="text-[11px] text-muted-foreground">类别</span>
        <button
          type="button"
          class="cursor-pointer rounded-full px-2.5 py-1 text-[12px] transition-colors"
          :class="fCategory === ''
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground hover:text-foreground'"
          @click="fCategory = ''"
        >
          全部
        </button>
        <button
          v-for="c in CATEGORIES"
          :key="c"
          type="button"
          class="cursor-pointer rounded-full px-2.5 py-1 text-[12px] transition-colors"
          :class="fCategory === c
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground hover:text-foreground'"
          @click="fCategory = fCategory === c ? '' : c"
        >
          {{ c }}<span class="ml-1 tabular-nums opacity-70">{{ categoryCounts[c] ?? 0 }}</span>
        </button>

        <label class="ml-auto flex cursor-pointer items-center gap-1.5 text-[11.5px] text-muted-foreground">
          <input v-model="onlyNoActor" type="checkbox" class="h-3.5 w-3.5 cursor-pointer accent-primary">
          仅看未记录操作者（{{ noActor }}）
        </label>
        <span class="basis-full text-[11px] text-muted-foreground">
          类别与「仅看未记录」在<strong>当前已加载的 {{ items.length }} 条</strong>内筛选（后端不支持这两维）；
          动作 / 结果 / 操作者 / 关键字仍由服务端筛选。
        </span>
      </div>
    </Card>

    <p v-if="err" class="mb-3 text-[11.5px] text-destructive">{{ err }}</p>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <Card v-else-if="visible.length" padding="none">
      <!-- 表头 -->
      <div
        class="hidden items-center gap-3 border-b border-border px-4 py-2.5 text-[11px] text-muted-foreground lg:flex"
      >
        <span class="w-36 shrink-0">时间</span>
        <span class="w-20 shrink-0">操作者</span>
        <span class="w-20 shrink-0">类别</span>
        <span class="w-16 shrink-0">动作</span>
        <span class="w-14 shrink-0">结果</span>
        <span class="min-w-0 flex-1">文件 / 详情</span>
      </div>

      <div
        v-for="(i, idx) in visible"
        :key="idx"
        class="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <span class="w-36 shrink-0 font-mono text-[11.5px] text-muted-foreground tabular-nums">
          {{ str(i, 'ts') }}
        </span>

        <span
          class="w-20 shrink-0 truncate text-[11.5px]"
          :class="actorOf(i) === '未记录' ? 'text-muted-foreground/70 italic' : 'text-foreground'"
          :title="str(i, 'actor') ? `操作者：${str(i, 'actor')}` : '该条目没有操作者记录（历史数据或未鉴权路径）'"
        >
          {{ actorOf(i) }}
        </span>

        <span class="w-20 shrink-0 text-[11.5px] text-muted-foreground">
          {{ categoryOf(i.action) }}
        </span>

        <span class="w-16 shrink-0 text-[12px] font-medium text-foreground">
          {{ str(i, 'action') || '—' }}
        </span>

        <span class="w-14 shrink-0">
          <Badge :tone="str(i, 'status') === '失败' ? 'err' : 'ok'">
            {{ str(i, 'status') || '—' }}
          </Badge>
        </span>

        <span class="min-w-0 flex-1 basis-full text-[12px] leading-relaxed lg:basis-auto">
          <span class="text-foreground">{{ str(i, 'file') || '—' }}</span>
          <span v-if="str(i, 'output')" class="text-muted-foreground"> → {{ str(i, 'output') }}</span>
          <span v-if="str(i, 'detail')" class="block text-[11.5px] text-muted-foreground">
            {{ str(i, 'detail') }}
          </span>
        </span>
      </div>
    </Card>

    <Card v-else class="py-12 text-center text-[12.5px] text-muted-foreground">
      <template v-if="!items.length">没有符合条件的记录。</template>
      <template v-else>
        已加载的 {{ items.length }} 条里没有符合「{{ fCategory || '全部类别'
        }}{{ onlyNoActor ? ' · 仅未记录操作者' : '' }}」的条目 —— 可放宽类别筛选，或点「加载更多」扩大范围。
      </template>
    </Card>

    <!-- 加载更多：后端只有 limit、没有 offset，故抬高 limit 重取 -->
    <div v-if="!loading && items.length" class="mt-3 flex flex-wrap items-center justify-center gap-2">
      <Button :disabled="!canLoadMore" @click="loadMore">
        {{ canLoadMore ? `加载更多（当前 ${items.length} 条）` : `已到单次上限（${items.length} 条）` }}
      </Button>
      <span class="text-[11.5px] text-muted-foreground">
        单次最多 {{ LOAD_STEPS[LOAD_STEPS.length - 1] }} 条；更早的记录请用「下载 activity.log」
      </span>
    </div>

    <!-- 无操作者记录时的解释：避免被误解为「系统没记」 -->
    <Card v-if="!loading && noActor" class="mt-4" padding="sm">
      <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        <span>
          有 {{ noActor }} 条记录没有操作者：其中历史条目产生于「操作者字段」上线之前，
          其余来自不强制鉴权的旧接口（`/convert` 等）。这些条目一律显示为「未记录」，
          不做推测。
        </span>
      </div>
    </Card>

    <!-- 留存策略（第 52 期）：默认关闭 = 单文件一直追加；开启后按大小轮转，读取跨归档 -->
    <Card class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">留存策略</span>
        <span class="text-[11.5px] text-muted-foreground">
          当前 activity.log{{ storage ? `（${fmtBytes(storage.bytes)}）` : '' }}
          <template v-if="storage && storage.archives">
            · 已归档 {{ storage.archives }} 份
          </template>
        </span>
        <Button size="sm" class="ml-auto" :disabled="saving" @click="saveRetention">
          {{ saving ? '保存中…' : '保存留存设置' }}
        </Button>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="flex items-center gap-3">
          <div class="min-w-0 flex-1">
            <div class="text-[12.5px] font-medium text-foreground">按大小轮转</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">
              开启后，当前日志超过上限就滚动成带时间戳的归档（可选压缩），只保留最近几份；
              读取会跨归档，列表仍连续。不开启就是原来的「单文件一直追加」
            </div>
          </div>
          <button
            type="button"
            role="switch"
            :aria-checked="retEnabled"
            class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
            :class="retEnabled ? 'bg-primary' : 'bg-muted'"
            @click="setRet('enabled', !retEnabled)"
          >
            <span
              class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
              :class="retEnabled ? 'translate-x-[16px]' : 'translate-x-[2px]'"
            />
          </button>
        </div>
      </div>

      <div class="flex flex-wrap items-end gap-4 px-4 py-3.5" :class="retEnabled ? '' : 'opacity-55'">
        <label class="text-[12px] text-muted-foreground">
          <span class="mb-1 block text-[12.5px] font-medium text-foreground">单文件上限（MB）</span>
          <input
            :value="retMaxMb"
            type="number"
            min="1"
            max="100"
            step="1"
            class="h-8 w-24 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @change="setRet('max_bytes', Number(($event.target as HTMLInputElement).value || 1) * 1048576)"
          >
        </label>
        <label class="text-[12px] text-muted-foreground">
          <span class="mb-1 block text-[12.5px] font-medium text-foreground">保留归档份数</span>
          <input
            :value="retKeep"
            type="number"
            min="1"
            max="50"
            step="1"
            class="h-8 w-24 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @change="setRet('keep', Math.max(1, Number(($event.target as HTMLInputElement).value || 1)))"
          >
        </label>
        <label class="flex cursor-pointer items-center gap-2 pb-2 text-[12.5px] text-foreground">
          <input
            :checked="retCompress"
            type="checkbox"
            class="h-4 w-4 cursor-pointer accent-primary"
            @change="setRet('compress', ($event.target as HTMLInputElement).checked)"
          >
          归档时压缩（gzip）
        </label>
        <p class="basis-full text-[11.5px] text-muted-foreground">
          归档就在日志目录里（<span class="font-mono">{{ storage?.retention ? 'activity-*.log / .jsonl' : 'activity-*.log / .jsonl' }}</span>）；
          「下载 activity.log」给的是当前文件，归档请到日志目录取。
        </p>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="Audit Log"
      :groups="['类别与详情结构', '留存与合规']"
      :items="[
        '上游有独立的审计子系统与类别体系（Authentication / Books / Libraries / Settings / Integrations）',
        '上游的 Details 列是结构化对象（如 Book #301 / Library #3），本项目是自由文本',
        '上游按「账号 + 设备 + 会话」维度记录（如 Stromboid#1），本项目只有账号名',
      ]"
      note="本项目复用活动日志作为审计视图：类别由动作归并得出，不是独立体系；操作者字段为后续新增，历史条目缺失属正常。筛选维度：动作 / 结果 / 操作者 / 关键字走服务端，类别与「仅看未记录操作者」走客户端（作用范围 = 当前已加载条目）。第 50 期起支持「加载更多」（抬高 limit）与「导出当前筛选结果为 CSV」；第 52 期起支持留存策略（按大小轮转 / 保留 N 份 / 可选压缩，默认关闭）。"
    />
  </div>
</template>
