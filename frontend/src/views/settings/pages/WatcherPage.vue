<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import { WATCHER_FIELDS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type HealthInfo, type WatcherStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * EXTENSIONS → Watcher（`/settings/ext/watcher`）
 *
 * 本项目独有分区：上游的监听只是「每书库一个 Watch folders 开关」，
 * 没有本项目这 9 项轮询 / 稳定判定参数与维护动作。
 */

interface WatcherInfo extends WatcherStatus {
  input?: string
  output?: string
  interval?: number
  processed?: number
  failed?: number
}

const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection, ignoreText } = useSettingsConfig()

const watcher = ref<WatcherInfo | null>(null)
const health = ref<HealthInfo | null>(null)

async function refreshRuntime(): Promise<void> {
  try {
    watcher.value = (await api.watcherStatus()) as WatcherInfo
  } catch {
    /* 运行状态取不到时不阻塞表单 */
  }
}

async function toggleWatcher(): Promise<void> {
  try {
    if (watcher.value?.running) await api.watcherStop()
    else await api.watcherStart()
    ui.toast(watcher.value?.running ? '监听已停止' : '监听已启动')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  }
  await refreshRuntime()
}

async function scanNow(): Promise<void> {
  try {
    await api.scanNow()
    ui.toast('已触发一次扫描')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  }
  await refreshRuntime()
}

async function clearCache(): Promise<void> {
  if (!window.confirm('清空缓存？（AI 分章缓存 + 监听状态，不影响成品）')) return
  try {
    const r = await api.clearCache()
    ui.toast(`已清理 ${r.removed} 项缓存`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '清理失败')
  }
}

async function clearLogs(): Promise<void> {
  if (!window.confirm('清空活动日志？（仅清空记录，不影响文件）')) return
  try {
    await api.clearLogs()
    ui.toast('日志已清空')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '清空失败')
  }
}

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch {
    /* ignore */
  }
  await loadConfig()
  await refreshRuntime()
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">监听</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Watcher</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">输入目录自动处理与维护</span>
      <Button
        size="sm"
        variant="primary"
        class="ml-auto"
        :disabled="saving"
        @click="saveSection('watcher')"
      >保存</Button>
    </div>

    <!-- 运行状态 -->
    <Card padding="none" class="mb-4">
      <div class="flex items-center gap-3 border-b border-border px-4 py-3.5">
        <span class="h-2 w-2 shrink-0 rounded-full" :class="watcher?.running ? 'bg-success' : 'bg-muted-foreground'" />
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">监听状态</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            {{ watcher?.running ? '运行中' : '未运行' }}
            <span v-if="watcher?.interval"> · 间隔 {{ watcher.interval }}s</span>
            <span v-if="watcher?.processed !== undefined"> · 已处理 {{ watcher.processed }}</span>
            <span v-if="watcher?.failed"> · 失败 {{ watcher.failed }}</span>
          </div>
        </div>
        <Button size="sm" @click="scanNow">立即扫描</Button>
        <Button size="sm" :variant="watcher?.running ? 'danger' : 'primary'" @click="toggleWatcher">
          {{ watcher?.running ? '停止' : '启动' }}
        </Button>
      </div>

      <div class="border-b border-border px-4 py-3">
        <div class="text-[13px] font-medium text-foreground">目录</div>
        <dl class="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
          <div
            v-for="d in [
              { k: '输入', v: health?.input ?? watcher?.input ?? '—' },
              { k: '导出', v: health?.output ?? watcher?.output ?? '—' },
              { k: '日志', v: health?.logs ?? '—' },
            ]"
            :key="d.k"
            class="min-w-0"
          >
            <dt class="text-[11px] text-muted-foreground">{{ d.k }}</dt>
            <dd class="truncate font-mono text-[11.5px] text-foreground">{{ d.v }}</dd>
          </div>
        </dl>
      </div>

      <div class="flex flex-wrap items-center gap-2 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">维护</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">清缓存不影响成品；日志可在「工具 → 日志」查看</div>
        </div>
        <Button size="sm" @click="clearCache">清空缓存</Button>
        <Button size="sm" variant="danger" @click="clearLogs">清空日志</Button>
      </div>
    </Card>

    <!-- 监听参数 -->
    <Card padding="none">
      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in WATCHER_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />

        <div class="px-4 py-3">
          <div class="mb-1.5 text-[13px] font-medium text-foreground">忽略规则</div>
          <div class="mb-2 text-[11.5px] text-muted-foreground">
            每行一条 fnmatch，如 <code class="font-mono">*.tmp</code>
          </div>
          <textarea
            v-model="ignoreText"
            rows="5"
            class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          />
        </div>
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <Card v-if="watcher?.input || health?.input" class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游把同类能力放在
        <RouterLink to="/settings/admin/book-dock" class="underline">服务端 → Book Dock</RouterLink>
        （投递目录 + 自动抓取元数据 + 置信度达标自动定稿）。
        两者语义相近，但本页多了轮询 / 稳定判定等面向网络挂载的参数。
      </div>
    </Card>
  </div>
</template>
