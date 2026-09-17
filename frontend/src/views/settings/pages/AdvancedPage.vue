<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type BackupItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * EXTENSIONS → Advanced（`/settings/ext/advanced`）
 *
 * 本项目独有分区：上游不提供「直接编辑配置文件」的入口。
 * 保留它是设置失效时的安全网（覆盖层提示 + 原文编辑 + 备份还原）。
 *
 * 原文与备份状态属于本页局部，不进共享 composable。
 */

const ui = useUiStore()
const { files, overridden, loadConfig, clearOverrides } = useSettingsConfig()

const rawText = ref('')
const rawInfo = ref<{ path: string; mtime: number; size: number; exists: boolean }>({
  path: '',
  mtime: 0,
  size: 0,
  exists: false,
})
const rawLoading = ref(false)
const rawSaving = ref(false)
const rawError = ref('')
const rawOk = ref('')
const backups = ref<BackupItem[]>([])

async function loadRaw(): Promise<void> {
  rawLoading.value = true
  rawError.value = ''
  try {
    const r = await api.getRawConfig()
    rawText.value = r.text
    rawInfo.value = { path: r.path, mtime: r.mtime, size: r.size, exists: r.exists }
  } catch (e) {
    rawError.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    rawLoading.value = false
  }
}

async function loadBackups(): Promise<void> {
  try {
    backups.value = (await api.listBackups()).items
  } catch {
    /* ignore */
  }
}

async function saveRaw(): Promise<void> {
  rawError.value = ''
  rawOk.value = ''
  rawSaving.value = true
  try {
    const r = await api.saveRawConfig(rawText.value)
    rawOk.value = r.backup ? `已保存（已备份为 ${r.backup}）` : '已保存'
    await loadRaw()
    await loadBackups()
    await loadConfig(true)
  } catch (e) {
    rawError.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    rawSaving.value = false
  }
}

async function restoreBackup(name: string): Promise<void> {
  if (!window.confirm(`还原到备份「${name}」？（当前内容会先自动备份）`)) return
  try {
    await api.restoreBackup(name)
    ui.toast('已还原到该备份')
    await loadRaw()
    await loadBackups()
    await loadConfig(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '还原失败')
  }
}

async function resetRaw(): Promise<void> {
  if (!window.confirm('重置为内置默认配置？（当前内容会先自动备份；config.yaml 的注释会丢失）')) return
  try {
    await api.resetConfig()
    ui.toast('已重置为默认配置')
    await loadRaw()
    await loadBackups()
    await loadConfig(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '重置失败')
  }
}

function fmtTime(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

onMounted(async () => {
  await loadConfig()
  await loadRaw()
  await loadBackups()
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">高级</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Advanced</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">直接编辑 config.yaml 原文</span>
      <Button size="sm" class="ml-auto" :disabled="rawLoading" @click="loadRaw">重新加载</Button>
      <Button size="sm" variant="primary" :disabled="rawSaving || rawLoading" @click="saveRaw">保存</Button>
    </div>

    <!-- 覆盖层提示：避免「改了 yaml 却不生效」 -->
    <Card v-if="overridden.length" class="mb-4">
      <div class="flex flex-wrap items-center gap-2">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0 text-warning" />
        <span class="text-[12.5px] text-foreground">
          有 {{ overridden.length }} 项被上方分区的「覆盖层」压过，改 config.yaml 不会生效：
        </span>
        <span
          v-for="k in overridden"
          :key="k"
          class="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
        >{{ k }}</span>
        <Button size="sm" variant="danger" class="ml-auto" @click="clearOverrides">清除覆盖层</Button>
      </div>
    </Card>

    <Card padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="truncate font-mono text-[11.5px] text-muted-foreground">
          {{ rawInfo.path || files.config_file }}
        </span>
        <Badge v-if="!rawInfo.exists" tone="warn">文件不存在（保存后创建）</Badge>
        <span v-else class="text-[11px] text-muted-foreground tabular-nums">
          {{ fmtTime(rawInfo.mtime) }} · {{ rawInfo.size }} B
        </span>
        <span class="ml-auto text-[11px] text-muted-foreground">保存前自动备份到 backups/</span>
      </div>

      <div class="px-4 py-3">
        <textarea
          v-model="rawText"
          rows="18"
          spellcheck="false"
          aria-label="config.yaml 内容"
          class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
          :placeholder="rawLoading ? '加载中…' : ''"
        />
        <p v-if="rawError" class="mt-2 text-[11.5px] text-destructive">{{ rawError }}</p>
        <p v-else-if="rawOk" class="mt-2 text-[11.5px] text-success">{{ rawOk }}</p>
        <p v-else class="mt-2 text-[11px] text-muted-foreground">
          注意：直接编辑会丢失 config.yaml 的注释与排版；保存前会自动备份，可随时还原。
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        <span class="text-[12.5px] font-medium text-foreground">重置</span>
        <span class="text-[11.5px] text-muted-foreground">恢复为内置默认配置（重置前自动备份）</span>
        <Button size="sm" variant="danger" class="ml-auto" @click="resetRaw">重置为默认</Button>
      </div>
    </Card>

    <Card padding="none" class="mt-4">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">备份</h3>
        <span class="text-[11.5px] text-muted-foreground">共 {{ backups.length }} 份</span>
        <Button size="sm" class="ml-auto" @click="loadBackups">刷新</Button>
      </div>
      <p v-if="!backups.length" class="px-4 py-4 text-[12px] text-muted-foreground">暂无备份。</p>
      <div
        v-for="b in backups"
        :key="b.name"
        class="flex items-center gap-3 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <span class="min-w-0 flex-1 truncate font-mono text-[11.5px] text-foreground">{{ b.name }}</span>
        <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ fmtTime(b.mtime) }}</span>
        <Button size="sm" @click="restoreBackup(b.name)">还原</Button>
      </div>
    </Card>

    <p class="mt-4 text-[11px] leading-relaxed text-muted-foreground">
      上游 BookOrbit 不提供直接编辑配置文件的入口，本页属本项目自有安全网（对齐迁移时保留）。
    </p>
  </div>
</template>
