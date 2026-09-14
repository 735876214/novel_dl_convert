<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type LogItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** 转换日志：列表 + 关键词/状态过滤 + 下载 + 清空。接真实 /api/logs */
const ui = useUiStore()

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

onMounted(load)

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
    <PageHead title="转换日志" :desc="`共 ${total} 条记录${logDir ? ` · ${logDir}` : ''}`" />

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

    <Card v-else-if="items.length" padding="none" class="overflow-x-auto">
      <table class="w-full min-w-[46rem] border-collapse text-left">
        <thead>
          <tr class="border-b border-border">
            <th class="px-4 py-2.5 text-[11px] font-semibold text-muted-foreground">时间</th>
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
    </Card>

    <EmptyState v-else icon="note" title="没有日志记录" desc="转换、下载与监听动作都会写进这里。" />
  </div>
</template>
