<script setup lang="ts">
import { onActivated, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import ScrapePanel from '@/components/tools/ScrapePanel.vue'
import { api, type LogItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 转换日志页，两个子标签（第 18 期）：
 * - **日志**：转换 / 添加 / 刮削的流水（列表 + 过滤 + 下载 + 清空），接 /api/logs；
 * - **刮削**：刮削出版的进展、结果与失败手动整理（接 /api/scrape/*）。
 *
 * 两件事放在同一页是因为它们回答的是同一个问题：「我刚丢进去的书，现在怎么样了？」
 * —— 流水说「做过什么」，刮削面板说「成品对不对、要不要我插手」。
 */
const ui = useUiStore()

type Tab = 'log' | 'scrape'
const tab = ref<Tab>('log')

const TABS: Array<{ value: Tab; label: string }> = [
  { value: 'log', label: '日志' },
  { value: 'scrape', label: '刮削' },
]

const items = ref<LogItem[]>([])
const total = ref(0)
const logDir = ref('')
const keyword = ref('')
const status = ref('')
const loading = ref(false)

function load(): void {
  loading.value = true
  api
    .logs({ limit: 300, q: keyword.value, status: status.value })
    .then((r) => {
      items.value = r.items ?? []
      // count 可能是数字，也可能是聚合对象（后端实现如此），统一归一化成数字
      total.value = typeof r.count === 'number' ? r.count : (r.items?.length ?? 0)
      logDir.value = r.dir ?? ''
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
// 只在「日志」标签下请求 —— 刮削面板有自己的轮询与拉取，别替它白跑一遍。
onActivated(() => {
  if (tab.value === 'log') load()
})

watch(tab, (v) => {
  if (v === 'log') load()
})

function clearAll(): void {
  api
    .clearLogs()
    .then(() => {
      ui.toast('日志已清空')
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
}

function toneOf(s: string | undefined): 'ok' | 'err' | 'warn' | 'neutral' {
  if (!s) return 'neutral'
  if (s.includes('成功') || s === 'ok' || s === 'success') return 'ok'
  if (s.includes('失败') || s === 'error' || s === 'fail') return 'err'
  return 'warn'
}

function cell(row: LogItem, key: string): string {
  const v = row[key]
  return v === undefined || v === null ? '—' : String(v)
}

/** 日志文件下载走浏览器原生下载（Vue 模板里不能直接访问 window，必须包一层） */
function downloadLogs(): void {
  window.open(api.logsDownloadUrl(), '_blank')
}
</script>

<template>
  <div>
    <!-- 子标签：日志（做过什么） / 刮削（成品对不对、要不要插手） -->
    <div class="mb-4 flex gap-4 border-b border-border" role="tablist">
      <button
        v-for="t in TABS"
        :key="t.value"
        type="button"
        role="tab"
        :aria-selected="tab === t.value"
        class="-mb-px cursor-pointer border-b-2 px-0.5 pb-2 text-[13px] font-medium transition-colors"
        :class="
          tab === t.value
            ? 'border-primary text-foreground'
            : 'border-transparent text-muted-foreground hover:text-foreground'
        "
        @click="tab = t.value"
      >
        {{ t.label }}
      </button>
    </div>

    <template v-if="tab === 'log'">
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <input
        v-model="keyword"
        type="text"
        placeholder="按书名或关键词筛选…"
        aria-label="日志关键词"
        class="h-8 w-64 rounded-md border border-border bg-muted px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        @keydown.enter="load"
      >
      <select
        v-model="status"
        aria-label="按状态筛选"
        class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
        @change="load"
      >
        <option value="">全部状态</option>
        <option value="ok">成功</option>
        <option value="error">失败</option>
      </select>
      <Button variant="primary" :disabled="loading" @click="load">查询</Button>
      <Button @click="downloadLogs">下载日志</Button>
      <Button variant="danger" class="ml-auto" @click="clearAll">清空</Button>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <Card v-else-if="items.length" padding="none">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">转换日志</h3>
        <span class="max-w-[36rem] truncate text-[11.5px] text-muted-foreground" :title="logDir">
          共 {{ total }} 条记录{{ logDir ? ` · ${logDir}` : '' }}
        </span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full min-w-[46rem] border-collapse text-left">
          <thead>
            <tr class="border-b border-border">
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">时间</th>
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">操作者</th>
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">动作</th>
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">目标</th>
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">状态</th>
              <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">详情</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in items"
              :key="i"
              class="border-b border-border/60 last:border-b-0 transition-colors hover:bg-muted/50"
            >
              <td class="px-4 py-2 text-[11.5px] whitespace-nowrap text-muted-foreground tabular-nums">
                {{ cell(row, 'ts') !== '—' ? cell(row, 'ts') : cell(row, 'time') }}
              </td>
              <!-- 操作者：历史条目没有该字段（字段后加），显示「未记录」而不臆测 -->
              <td
                class="px-4 py-2 text-[11.5px] whitespace-nowrap"
                :class="cell(row, 'actor') === '—' ? 'text-muted-foreground/70 italic' : 'text-foreground'"
                title="早于「操作者字段」上线的条目、以及未鉴权旧接口写入的条目没有操作者"
              >
                {{ cell(row, 'actor') === '—' ? '未记录' : cell(row, 'actor') }}
              </td>
              <td class="px-4 py-2 text-[12px] text-foreground">{{ cell(row, 'action') }}</td>
              <td class="max-w-[16rem] truncate px-4 py-2 text-[12px] text-foreground" :title="cell(row, 'target')">
                {{ cell(row, 'target') !== '—' ? cell(row, 'target') : cell(row, 'file') }}
              </td>
              <td class="px-4 py-2">
                <Badge :tone="toneOf(row.status)">{{ row.status ?? '—' }}</Badge>
              </td>
              <td class="max-w-[22rem] truncate px-4 py-2 text-[11.5px] text-muted-foreground" :title="cell(row, 'message')">
                {{ cell(row, 'message') }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <EmptyState v-else icon="note" title="没有日志记录" desc="转换、下载与监听动作都会写进这里。" />
    </template>

    <!-- 刮削出版：进展 / 结果 / 待确认与失败的人工整理（第 18 期） -->
    <ScrapePanel v-else />
  </div>
</template>
