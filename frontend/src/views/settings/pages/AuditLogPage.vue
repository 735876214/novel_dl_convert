<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { api, type LogItem } from '@/lib/api'

/**
 * SERVER → Audit Log（`/settings/admin/audit-log`）
 *
 * 真实现：直接读活动日志（`GET /api/logs`），把「谁做的」显示出来。
 * 「操作者」来自后端新增的 `actor` 字段（由鉴权中间件注入，见 `core/activity_log.py`）。
 *
 * 与上游的差异：上游是独立的审计子系统（操作者 / 类别 / Details / 筛选器齐全）；
 * 本项目复用活动日志，**类别由动作归并**，且没有独立的历史留存策略。
 * 历史条目没有 actor 字段 —— 一律按「未记录」渲染，不报错、不臆测。
 */

const items = ref<LogItem[]>([])
const loading = ref(true)
const err = ref('')

const fAction = ref('')
const fStatus = ref('')
const fQ = ref('')

const ACTIONS = ['转换', '添加', '跳过', '重命名', '清理']
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
      limit: 200,
      action: fAction.value || undefined,
      status: fStatus.value || undefined,
      q: fQ.value.trim() || undefined,
    })
    items.value = r.items
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
  void load()
}

onMounted(load)

const okCount = computed(() => items.value.filter((i) => String(i.status) === '成功').length)
const failCount = computed(() => items.value.filter((i) => String(i.status) === '失败').length)
/** actor 为空的条数：历史条目（字段缺失）或未鉴权路径写入 */
const noActor = computed(
  () => items.value.filter((i) => !String(i.actor ?? '').trim()).length,
)

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
        共 {{ items.length }} 条 · 成功 {{ okCount }} · 失败 {{ failCount }}
      </span>
      <Button size="sm" class="ml-auto" :disabled="loading" @click="load">刷新</Button>
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
    </Card>

    <p v-if="err" class="mb-3 text-[11.5px] text-destructive">{{ err }}</p>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <Card v-else-if="items.length" padding="none">
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
        v-for="(i, idx) in items"
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
      没有符合条件的记录。
    </Card>

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

    <SettingsUnsupportedCard
      label="Audit Log"
      :groups="['类别与详情结构', '留存与合规']"
      :items="[
        '上游有独立的审计子系统与类别体系（Authentication / Books / Libraries / Settings / Integrations）',
        '上游的 Details 列是结构化对象（如 Book #301 / Library #3），本项目是自由文本',
        '上游按「账号 + 设备 + 会话」维度记录（如 Stromboid#1），本项目只有账号名',
        '审计记录的留存策略与导出格式（本项目仅保留单个 activity.log / .jsonl 并支持下载）',
        '按操作者筛选（本项目已记录 actor，但日志接口尚未支持按 actor 过滤）',
      ]"
      note="本项目复用活动日志作为审计视图：类别由动作归并得出，不是独立体系；操作者字段是本次新增，历史条目缺失属正常。"
    />
  </div>
</template>
