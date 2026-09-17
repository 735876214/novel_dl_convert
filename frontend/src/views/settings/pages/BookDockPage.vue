<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type HealthInfo, type WatcherStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * SERVER → Book Dock（`/settings/admin/book-dock`）
 *
 * 真实现：投递目录 = 本项目的 `INPUT_DIR`，与目录监听是同一套东西 ——
 * 把文件丢进去就会被自动处理。本页把「目录 + 监听状态 + 自动处理开关 + 处理计数」
 * 聚合展示（与上游 Book Dock 的「投递目录 + 自动处理」高度同构）。
 *
 * 上游还有「元数据自动抓取」与「按置信度自动定稿」——本项目没有元数据抓取体系，
 * 这两项明确标注未支持，并写明依赖条件。
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

async function refresh(): Promise<void> {
  try {
    watcher.value = (await api.watcherStatus()) as WatcherInfo
  } catch {
    /* 状态取不到时不阻塞页面 */
  }
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

onMounted(async () => {
  try {
    health.value = await api.health()
  } catch {
    /* ignore */
  }
  await loadConfig()
  await refresh()
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

    <SettingsUnsupportedCard
      label="Book Dock"
      :groups="['METADATA', 'AUTO-FINALIZE', '状态机']"
      :items="[
        'Auto-fetch metadata from providers（投递后自动抓取元数据）—— 依赖元数据抓取体系，本项目尚无',
        'Enable auto-finalize（元数据置信度达阈值自动定稿）—— 依赖置信度评分体系，本项目尚无',
        '五态流水线：All / Needs review / Pending / Ready / Error',
        '整页拖拽投递（本项目仅工具页的本地转换支持 .txt 拖拽）',
        '按条目的重新扫描 / 忽略 / 删除等单项操作',
      ]"
      note="上游 Book Dock 是「投递目录 + 元数据抓取 + 置信度定稿」的完整流水线；本项目只具备其中的「投递目录 + 自动处理」部分，等价物就是输入目录监听。前两项待元数据体系落地后再补。"
    />

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游对应入口：侧栏 <span class="font-mono">Book Dock</span>。
        相关页：<RouterLink to="/settings/ext/watcher" class="underline">监听</RouterLink>（
        轮询与稳定判定参数）、<RouterLink to="/tools/local" class="underline">工具 → 本地转换</RouterLink>（单文件投递）。
      </div>
    </Card>
  </div>
</template>
