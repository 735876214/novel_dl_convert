<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type BookDockResponse, type HealthInfo, type WatcherStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * SERVER → Book Dock（`/settings/admin/book-dock`）
 *
 * 真实现：投递目录 = 本项目的 `INPUT_DIR`，与目录监听是同一套东西 ——
 * 把文件丢进去就会被自动处理。本页把「目录 + 监听状态 + 自动处理开关 + 处理计数」
 * 聚合展示（与上游 Book Dock 的「投递目录 + 自动处理」高度同构）。
 *
 * 上游还有两组：METADATA 的「投递后自动抓元数据」本项目**已实现**（`metadata_fetch.auto_on_import`
 * 与 `metadata_fetch.enabled` 双重门控，见 core/watcher.py:84；开关在 设置 → 元数据），
 * AUTO-FINALIZE 的「按置信度无人值守定稿」未做（缺的是上游那组目标库 / 文件夹 / 合并模式配置）。
 *
 * 参数细节（轮询间隔 / 稳定判定 / 忽略规则等）在「本项目扩展 → 监听」，本页不重复。
 */

interface WatcherInfo extends WatcherStatus {
  input?: string
  output?: string
  interval?: number
  processed?: number
  failed?: number
  converted?: number
  added?: number
  scans?: number
}

const ui = useUiStore()
const { cfg, val, setVal, loadConfig, saveSection, saving } = useSettingsConfig()

const watcher = ref<WatcherInfo | null>(null)
const health = ref<HealthInfo | null>(null)

const dropDir = computed(() => health.value?.input ?? watcher.value?.input ?? '—')
const running = computed(() => Boolean(watcher.value?.running))
/** 自动处理开关：等价于「丢进去就自动转换 / 导出」 */
const autoProcess = computed(() => Boolean(val('watcher.enabled')))
const dirty = computed(() => cfg.value != null && autoProcess.value !== running.value)

const counters = computed(() => [
  { k: '已转换', v: watcher.value?.converted ?? watcher.value?.processed ?? 0 },
  { k: '已添加', v: watcher.value?.added ?? 0 },
  { k: '失败', v: watcher.value?.failed ?? 0 },
  { k: '扫描轮次', v: watcher.value?.scans ?? 0 },
])

// ---- 五态流水线（B3）：All / Needs review / Pending / Ready / Error ----
const dock = ref<BookDockResponse | null>(null)
const activeTab = ref('all')
const busyId = ref('')

const STATUS_LABEL: Record<string, string> = {
  pending: '待处理',
  ready: '就绪',
  needs_review: '待复核',
  error: '出错',
  ignored: '已忽略',
}
const STATUS_TONE: Record<string, 'neutral' | 'ok' | 'warn' | 'err'> = {
  pending: 'neutral',
  ready: 'ok',
  needs_review: 'warn',
  error: 'err',
  ignored: 'neutral',
}

function fmtSize(n: number): string {
  const b = Number(n) || 0
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}

async function loadDock(): Promise<void> {
  try {
    dock.value = await api.bookDock(activeTab.value)
  } catch {
    /* 列表取不到时不阻塞上方开关 */
  }
}

async function switchTab(key: string): Promise<void> {
  activeTab.value = key
  await loadDock()
}

/** 单项操作统一收尾：提示 + 重载（服务端已把新状态写回条目） */
async function act(fn: () => Promise<{ ok?: boolean }>, okMsg: string): Promise<void> {
  try {
    await fn()
    ui.toast(okMsg)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
  await refresh()
}

async function rescanItem(id: string): Promise<void> {
  busyId.value = id
  await act(() => api.bookDockRescan(id), '已重新处理')
  busyId.value = ''
}

async function ignoreItem(id: string): Promise<void> {
  busyId.value = id
  await act(() => api.bookDockIgnore(id), '已忽略该条目')
  busyId.value = ''
}

async function deleteItem(id: string): Promise<void> {
  if (!window.confirm('把该文件移出收书目录？\n\n文件会移入回收目录（不会真正删除），之后不再自动处理。')) {
    return
  }
  busyId.value = id
  await act(() => api.bookDockDelete(id), '已移出到回收目录')
  busyId.value = ''
}

async function refresh(): Promise<void> {
  try {
    watcher.value = (await api.watcherStatus()) as WatcherInfo
  } catch {
    /* 状态取不到时不阻塞页面 */
  }
  await loadDock()
}

async function toggleWatcher(): Promise<void> {
  try {
    if (running.value) await api.watcherStop()
    else await api.watcherStart()
    ui.toast(running.value ? '收书目录已暂停' : '收书目录已开始监听')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
  await refresh()
}

async function scanNow(): Promise<void> {
  try {
    await api.scanNow()
    ui.toast('已触发一次扫描')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  }
  await refresh()
}

async function saveAuto(): Promise<void> {
  const ok = await saveSection('watcher')
  // 开关变了要热更新监听器，后端保存时会一并处理，这里刷新状态即可
  if (ok) await refresh()
}

// ---- 整页拖拽投递（A8）：把文件拖进窗口即丢进 INPUT_DIR 处理 ----
const dragDepth = ref(0)
const dragging = computed(() => dragDepth.value > 0)
const dropping = ref(false)

function hasFiles(e: DragEvent): boolean {
  return Boolean(e.dataTransfer && [...e.dataTransfer.types].includes('Files'))
}
function onDragEnter(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth.value++
}
function onDragOver(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
}
function onDragLeave(e: DragEvent): void {
  if (!hasFiles(e)) return
  e.preventDefault()
  dragDepth.value = Math.max(0, dragDepth.value - 1)
}
async function onDrop(e: DragEvent): Promise<void> {
  if (!e.dataTransfer) return
  e.preventDefault()
  dragDepth.value = 0
  const files = [...e.dataTransfer.files]
  if (!files.length) return
  dropping.value = true
  let ok = 0
  for (const file of files) {
    try {
      await api.convertDrop(file)
      ok++
    } catch (err) {
      ui.toast(err instanceof Error ? `${file.name}：${err.message}` : `${file.name} 投递失败`)
    }
  }
  dropping.value = false
  if (ok) {
    ui.toast(`已投递 ${ok} 个文件到收书目录`)
    await refresh()
  }
}

onMounted(async () => {
  window.addEventListener('dragenter', onDragEnter)
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('dragleave', onDragLeave)
  window.addEventListener('drop', onDrop)
  try {
    health.value = await api.health()
  } catch {
    /* ignore */
  }
  await loadConfig()
  await refresh()
})

onBeforeUnmount(() => {
  window.removeEventListener('dragenter', onDragEnter)
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('dragleave', onDragLeave)
  window.removeEventListener('drop', onDrop)
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">收书目录</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Book Dock</span>
      <span class="text-[11.5px] text-muted-foreground">把文件丢进目录即自动处理</span>
      <Button size="sm" class="ml-auto" :disabled="saving" @click="scanNow">立即扫描</Button>
      <Button size="sm" :variant="running ? 'danger' : 'primary'" @click="toggleWatcher">
        {{ running ? '暂停' : '开始监听' }}
      </Button>
    </div>

    <!-- 投递目录 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3.5">
        <div class="flex items-center gap-3">
          <span class="h-2 w-2 shrink-0 rounded-full" :class="running ? 'bg-success' : 'bg-muted-foreground'" />
          <div class="min-w-0 flex-1">
            <div class="text-[13px] font-medium text-foreground">投递目录</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">
              {{ running ? '正在监听' : '未监听' }}
              <span v-if="watcher?.interval"> · 轮询 {{ watcher.interval }}s</span>
            </div>
          </div>
          <Badge :tone="running ? 'ok' : 'neutral'">{{ running ? '运行中' : '已暂停' }}</Badge>
        </div>
        <div class="mt-2 truncate rounded bg-muted px-2 py-1.5 font-mono text-[11.5px] text-foreground" :title="dropDir">
          {{ dropDir }}
        </div>
        <p class="mt-2 text-[11.5px] leading-relaxed text-muted-foreground">
          把 <code class="font-mono">.txt</code> 放进该目录会自动转成 EPUB 并归入成品目录；
          其它格式按设置原样导出。子目录是否递归、写入稳定判定等参数见
          <RouterLink to="/settings/ext/watcher" class="underline">本项目扩展 → 监听</RouterLink>。
        </p>
      </div>

      <!-- 自动处理开关 -->
      <div class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">自动处理投递文件</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            关闭后目录不再自动扫描，只能手动「立即扫描」或从工具页逐个处理
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="autoProcess"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="autoProcess ? 'bg-primary' : 'bg-muted'"
          @click="setVal('watcher.enabled', !autoProcess)"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="autoProcess ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
        <Button size="sm" variant="primary" :disabled="saving || !dirty" @click="saveAuto">保存</Button>
      </div>

      <!-- 计数 -->
      <div class="grid grid-cols-2 gap-x-4 gap-y-2 px-4 py-3.5 sm:grid-cols-4">
        <div v-for="c in counters" :key="c.k" class="min-w-0">
          <div class="text-[11px] text-muted-foreground">{{ c.k }}</div>
          <div class="mt-0.5 text-[13px] font-medium text-foreground tabular-nums">{{ c.v }}</div>
        </div>
      </div>
    </Card>

    <p v-if="dirty" class="mb-4 text-[11.5px] text-warning">
      开关已改动但尚未保存 —— 保存后监听器会立即按新配置启停。
    </p>

    <!-- 五态流水线（B3）：All / Needs review / Pending / Ready / Error -->
    <Card padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">投递流水线</h3>
        <span class="text-[11.5px] text-muted-foreground">条目按状态流转，可逐条复核</span>
        <div class="ml-auto flex flex-wrap items-center gap-1.5">
          <button
            v-for="t in dock?.tabs ?? []"
            :key="t.key"
            type="button"
            class="cursor-pointer rounded-full px-3 py-1 text-[12px] transition-colors"
            :class="activeTab === t.key
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted text-muted-foreground hover:text-foreground'"
            @click="switchTab(t.key)"
          >
            {{ t.label }}<span class="ml-1 tabular-nums opacity-70">{{ t.count }}</span>
          </button>
        </div>
      </div>

      <div v-if="dock && dock.items.length" class="divide-y divide-border">
        <div
          v-for="it in dock.items"
          :key="it.id"
          class="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <Icon name="book" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span class="truncate text-[12.5px] font-medium text-foreground" :title="it.name">{{ it.name }}</span>
              <Badge :tone="STATUS_TONE[it.status] ?? 'neutral'">
                {{ STATUS_LABEL[it.status] ?? it.status }}
              </Badge>
            </div>
            <div class="mt-1 truncate text-[11.5px] text-muted-foreground" :title="it.output || it.detail">
              {{ it.output ? `成品：${it.output}` : it.detail || '等待自动处理' }}
              <span class="ml-1 opacity-70">{{ fmtSize(it.size) }}</span>
              <span v-if="it.retries" class="ml-1 text-warning">· 已重试 {{ it.retries }} 次</span>
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            <Button size="sm" :disabled="busyId === it.id" @click="rescanItem(it.id)">重扫</Button>
            <Button size="sm" :disabled="busyId === it.id" @click="ignoreItem(it.id)">忽略</Button>
            <Button size="sm" variant="danger" :disabled="busyId === it.id" @click="deleteItem(it.id)">移出</Button>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        icon="upload"
        dashed
        class="m-4"
        :title="activeTab === 'all' ? '投递目录里还没有文件' : '该状态下没有条目'"
        desc="把 .txt / EPUB / PDF / CBZ 拖进本页任意位置，或直接放进投递目录，文件会在这里按状态流转。"
      />
    </Card>

    <SettingsUnsupportedCard
      label="Book Dock"
      :groups="['AUTO-FINALIZE']"
      :items="[
        'Enable auto-finalize（置信度达标即无人值守定稿）—— 上游开着后还要选 0–100 分阈值 / 目标库 / 元数据合并模式（safe_merge、embedded_only 等）/ 目标文件夹四项（上游 BookDockSettings.vue:207-287）；本项目入库目标是各库自己的来源目录（没有单点「目标库」设置），元数据侧的置信度阈值是 0–1 的**候选筛选**阈值、只决定哪些字段自动写回，两者不是一回事',
      ]"
      note="上游 Book Dock 是「投递目录 + 元数据抓取 + 置信度定稿」的完整流水线。本项目的「投递目录 + 自动处理 + 五态复核（待复核 / 待处理 / 就绪 / 出错）」已落地；投递即抓也已接线（metadata_fetch.auto_on_import，与 metadata_fetch.enabled 双重门控，开关在 设置 → 元数据），本卡只剩上游 auto-finalize 那组「目标库 / 文件夹 + 合并模式」配置未做。"
    />

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游对应入口：侧栏 <span class="font-mono">Book Dock</span>。
        相关页：<RouterLink to="/settings/ext/watcher" class="underline">监听</RouterLink>（
        轮询与稳定判定参数）、<RouterLink to="/tools/local" class="underline">工具 → 本地转换</RouterLink>（单文件投递）。
      </div>
    </Card>

    <!-- 整页拖拽投递遮罩（A8）：拖文件进窗口时浮层，松手即投递到收书目录 -->
    <transition
      enter-active-class="transition-opacity duration-150"
      leave-active-class="transition-opacity duration-150"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="dragging"
        class="fixed inset-0 z-[60] flex items-center justify-center bg-black/55 backdrop-blur-sm"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <div class="flex flex-col items-center gap-3 rounded-[var(--shell-radius)] border-2 border-dashed border-primary/60 bg-[var(--shell-surface)] px-10 py-9 text-center">
          <Icon name="upload" class="h-9 w-9 text-primary" />
          <div class="text-[15px] font-semibold text-foreground">松开投递到收书目录</div>
          <div class="text-[12px] text-muted-foreground">
            {{ dropping ? '正在处理…' : '.txt 会被转换，其它电子书格式（EPUB/PDF/CBZ 等）直接入库' }}
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>
