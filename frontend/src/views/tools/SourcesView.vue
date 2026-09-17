<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type SourceStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 书源管理：运行状态（Cookie / 可用性）+ 已注册列表 + 批量粘贴 + 文件上传。
 *
 * 状态来自 /api/sources/status（真实取得：Cookie 落盘情况 + download 配置约束），
 * 原「设置页」中的书源演示数据（成功率 / 延迟）已移除并归并到这里。
 */
const ui = useUiStore()

const sources = ref<SourceStatus[]>([])
const loading = ref(true)
const pasteText = ref('')
const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const stats = computed(() => {
  const total = sources.value.length
  const builtin = sources.value.filter((s) => !s.user).length
  const user = sources.value.filter((s) => s.user).length
  const cookie = sources.value.filter((s) => s.cookie.has).length
  const blocked = sources.value.filter((s) => !s.usable).length
  return { total, builtin, user, cookie, blocked }
})

const downloadEnabled = computed(() => sources.value[0]?.download_enabled ?? false)
const publicOnly = computed(() => sources.value[0]?.public_only ?? true)

function load(): void {
  loading.value = true
  api
    .sourcesStatus()
    .then((r) => {
      sources.value = r.items ?? []
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
onActivated(load)

function submitPaste(): void {
  const text = pasteText.value.trim()
  if (!text) {
    ui.toast('请先粘贴书源 JSON')
    return
  }
  busy.value = true
  api
    .addSourcesText(text)
    .then((r) => {
      ui.toast(`已添加 ${r.added ?? 0} 个书源`)
      pasteText.value = ''
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function onFilePick(e: Event): void {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  api
    .uploadSourcesFile(file)
    .then((r) => {
      ui.toast(`已从文件添加 ${r.added ?? 0} 个书源`)
      load()
    })
    .catch((err: Error) => ui.toast(err.message))
    .finally(() => {
      busy.value = false
      input.value = ''
    })
}

function remove(name: string): void {
  api
    .deleteSource(name)
    .then(() => {
      ui.toast(`已删除 ${name}`)
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
}

function fmtTime(ts: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 概览 -->
    <div class="grid grid-cols-2 gap-3 md:grid-cols-5">
      <Card v-for="c in [
        { label: '书源总数', value: stats.total, icon: 'source' },
        { label: '内置', value: stats.builtin, icon: 'library' },
        { label: '用户添加', value: stats.user, icon: 'user' },
        { label: '已持久化 Cookie', value: stats.cookie, icon: 'check' },
        { label: '当前不可用', value: stats.blocked, icon: 'alert' },
      ]" :key="c.label">
        <div class="flex items-center gap-2 text-muted-foreground">
          <Icon :name="c.icon" class="h-3.5 w-3.5" />
          <span class="text-[11.5px]">{{ c.label }}</span>
        </div>
        <div class="mt-1.5 text-[20px] leading-none font-semibold text-foreground tabular-nums">
          {{ c.value }}
        </div>
      </Card>
    </div>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <!-- 导入 -->
      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">导入书源</h3>
        <p class="mb-2.5 text-[11.5px] text-muted-foreground">
          支持 JSON 对象 / 数组 / JSONL 三种格式，一次可导入多个书源。
        </p>
        <textarea
          v-model="pasteText"
          rows="7"
          placeholder='{"name": "示例书源", "search": {"url": "..."}}'
          aria-label="粘贴书源 JSON"
          class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        />
        <div class="mt-2.5 flex items-center gap-2">
          <Button variant="primary" :disabled="busy" @click="submitPaste">导入</Button>
          <Button :disabled="busy" @click="fileInput?.click()">从文件导入</Button>
          <input ref="fileInput" type="file" accept=".json,.jsonl,.txt" class="hidden" @change="onFilePick">
        </div>
      </Card>

      <!-- 状态列表 -->
      <Card padding="none" class="lg:col-span-2">
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">书源状态</h3>
          <span class="text-[11.5px] text-muted-foreground">
            共 {{ stats.total }} 个 · 内置 {{ stats.builtin }} 个
          </span>
          <Badge class="ml-auto" :tone="downloadEnabled ? 'ok' : 'warn'">
            {{ downloadEnabled ? '下载已开启' : '下载未开启' }}
          </Badge>
          <Badge v-if="downloadEnabled" :tone="publicOnly ? 'neutral' : 'warn'">
            {{ publicOnly ? '仅公版源' : '全部源放行' }}
          </Badge>
        </div>

        <p v-if="!downloadEnabled" class="border-b border-border bg-muted/60 px-4 py-2 text-[11.5px] text-muted-foreground">
          下载功能当前关闭：在 <code class="font-mono">config.yaml</code> 设 <code class="font-mono">download.enabled: true</code> 后，书源才可用于搜索与下载。
        </p>

        <div v-if="loading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

        <div v-else-if="sources.length" class="max-h-[30rem] overflow-y-auto">
          <div
            v-for="s in sources"
            :key="s.name"
            class="flex items-start gap-3 border-b border-border/60 px-4 py-3 last:border-b-0"
          >
            <span
              class="mt-1 h-2 w-2 shrink-0 rounded-full"
              :class="s.usable ? 'bg-success' : 'bg-muted-foreground'"
              :title="s.usable ? '当前可用' : s.blocked_reason"
            />

            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="truncate text-[12.5px] font-medium text-foreground">{{ s.display_name || s.name }}</span>
                <Badge :tone="s.user ? 'accent' : 'neutral'">{{ s.user ? '用户' : '内置' }}</Badge>
                <Badge>{{ s.public ? '公版' : '私有' }}</Badge>
                <Badge v-if="s.cookie.has" tone="ok">已登录</Badge>
              </div>
              <p v-if="s.domains.length" class="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                {{ s.domains.join(' · ') }}
              </p>
              <p v-if="s.cookie.has" class="mt-0.5 text-[11px] text-muted-foreground">
                Cookie 已持久化 · {{ fmtTime(s.cookie.mtime) }}
              </p>
              <p v-if="!s.usable" class="mt-0.5 text-[11px] text-warning">{{ s.blocked_reason }}</p>
            </div>

            <Button
              v-if="s.user"
              size="sm"
              variant="danger"
              title="删除该书源"
              @click="remove(s.name)"
            >
              删除
            </Button>
            <span v-else class="shrink-0 pt-1 text-[11px] text-muted-foreground">内置不可删</span>
          </div>
        </div>

        <EmptyState v-else icon="source" title="还没有书源" desc="用左侧的批量粘贴或文件导入添加书源。" />
      </Card>
    </div>
  </div>
</template>
