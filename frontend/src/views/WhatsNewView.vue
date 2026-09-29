<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Card from '@/components/ui/Card.vue'
import PageHead from '@/components/ui/PageHead.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, apiErrorMessage, type ChangelogEntry, type UpdateStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** 新功能：应用内更新日志（数据源 = 后端解析的 CHANGELOG.md，离线可读）。 */
const ui = useUiStore()

/** 当前版本 + 版本列表（来自 CHANGELOG.md，按文件顺序：最新在前）。 */
const current = ref('')
const entries = ref<ChangelogEntry[]>([])
/** 远端检查快照（是否有更新 / 一键更新是否可用）。 */
const status = ref<UpdateStatus | null>(null)
/** 复制升级命令的反馈。 */
const copied = ref(false)
/** 立即更新后的阶段提示。 */
const applyMsg = ref('')
/** 搜索框（在当前所选版本内过滤条目）。 */
const query = ref('')
/** 当前选中的版本（默认当前版本，找不到则取第一个）。 */
const selected = ref('')

function compareVersion(a: string, b: string): number {
  const pa = a.replace(/^V/i, '').split('.').map((x) => parseInt(x, 10) || 0)
  const pb = b.replace(/^V/i, '').split('.').map((x) => parseInt(x, 10) || 0)
  const n = Math.max(pa.length, pb.length)
  for (let i = 0; i < n; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0)
    if (d) return d
  }
  return 0
}

/** 某版本是否比当前版本新（用于右侧「可更新」标记）。 */
function isNewer(v: string, base: string): boolean {
  if (!base) return false
  return compareVersion(v, base) > 0
}

const selectedEntry = computed<ChangelogEntry | null>(
  () => entries.value.find((e) => e.version === selected.value) || entries.value[0] || null,
)

/** 当前版本下、匹配搜索框的分组（搜索为空则原样）。 */
const filteredGroups = computed(() => {
  const e = selectedEntry.value
  if (!e) return []
  const q = query.value.trim().toLowerCase()
  if (!q) return e.groups
  return e.groups
    .map((g) => ({ tag: g.tag, items: g.items.filter((it) => it.toLowerCase().includes(q)) }))
    .filter((g) => g.items.length)
})

const isEmpty = computed(() => entries.value.length === 0)

function selectVersion(v: string): void {
  selected.value = v
  query.value = ''
}

async function applyUpdate(): Promise<void> {
  applyMsg.value = ''
  try {
    const r = await api.updateApply()
    if (r.ok) {
      applyMsg.value = '正在拉取最新镜像并重启容器，请稍候刷新页面…'
    } else {
      applyMsg.value = r.message || '更新不可用'
    }
  } catch (e) {
    applyMsg.value = apiErrorMessage(e, '更新失败')
  }
}

async function copyCommand(): Promise<void> {
  try {
    await navigator.clipboard.writeText('docker compose pull && docker compose up -d')
    copied.value = true
    setTimeout(() => (copied.value = false), 2000)
  } catch {
    ui.toast('复制失败，请手动执行：docker compose pull && docker compose up -d')
  }
}

onMounted(async () => {
  try {
    const c = await api.changelog()
    current.value = c.current
    entries.value = c.entries
    selected.value = c.entries.some((e) => e.version === c.current)
      ? c.current
      : (c.entries[0]?.version ?? '')
  } catch {
    current.value = ''
  }
  try {
    status.value = await api.updateStatus()
  } catch {
    status.value = null
  }
})
</script>

<template>
  <div>
    <PageHead title="新功能" :desc="`当前版本 v${current || '…'}`" />

    <EmptyState
      v-if="isEmpty"
      icon="bell"
      title="暂无更新记录"
      desc="新功能上线后会出现在这里。"
    />

    <template v-else>
      <!-- 有新版本：横幅提示 + 更新动作（挂了 socket 才真更新，否则给命令） -->
      <Card
        v-if="status?.has_update"
        padding="none"
        class="mb-4 border-l-2 border-primary"
      >
        <div class="flex flex-wrap items-center gap-3 px-4 py-3">
          <span class="text-[13px] text-foreground">
            有新版本 <span class="font-mono font-semibold text-primary">{{ status.latest }}</span> 可用
          </span>
          <!-- 第 80 期：自动更新真的会执行，所以横幅如实说明，别让用户以为只是提示 -->
          <span
            v-if="status.auto_apply && status.updater_available"
            class="text-[11.5px] text-muted-foreground"
          >已开启自动更新：下次检查会自动拉取并重建</span>
          <Button
            v-if="status.updater_available"
            size="sm"
            :disabled="!!applyMsg"
            @click="applyUpdate"
          >
            {{ applyMsg || '立即更新' }}
          </Button>
          <template v-else>
            <code class="rounded bg-muted px-2 py-1 text-[11.5px] text-foreground">docker compose pull && docker compose up -d</code>
            <Button size="sm" variant="ghost" @click="copyCommand">{{ copied ? '已复制' : '复制命令' }}</Button>
          </template>
          <a
            v-if="status.url"
            :href="status.url"
            target="_blank"
            rel="noreferrer"
            class="ml-auto text-[11.5px] text-muted-foreground underline"
          >查看 Release</a>
        </div>
      </Card>

      <div class="flex gap-6">
        <!-- 左：更新内容（所选版本的分组 + 搜索） -->
        <div class="min-w-0 flex-1">
          <div class="relative mb-3">
            <input
              v-model="query"
              type="text"
              placeholder="搜索更新内容…"
              class="h-[2rem] w-full rounded-md border border-border bg-card pr-3 pl-8 text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground focus:border-ring focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_22%,transparent)]"
            />
            <svg class="pointer-events-none absolute top-1/2 left-[0.625rem] h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.6-3.6" />
            </svg>
          </div>

          <template v-if="selectedEntry">
            <div class="mb-3 flex items-baseline gap-2">
              <span class="text-[15px] font-semibold text-foreground">{{ selectedEntry.version }}</span>
              <span v-if="selectedEntry.date" class="text-[12px] text-muted-foreground">{{ selectedEntry.date }}</span>
              <span
                v-if="selectedEntry.version === current"
                class="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary"
              >你在使用</span>
            </div>
            <p
              v-if="selectedEntry.note"
              class="mb-3 whitespace-pre-line text-[11.5px] leading-relaxed text-muted-foreground"
            >{{ selectedEntry.note }}</p>

            <div v-if="filteredGroups.length" class="space-y-4">
              <div v-for="g in filteredGroups" :key="g.tag">
                <h3 class="mb-1.5 text-[12px] font-semibold tracking-wide text-muted-foreground">{{ g.tag }}</h3>
                <ul class="space-y-1.5">
                  <li
                    v-for="item in g.items"
                    :key="item"
                    class="flex gap-2 text-[12.5px] text-foreground/90"
                  >
                    <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                    <span>{{ item }}</span>
                  </li>
                </ul>
              </div>
            </div>
            <p v-else class="text-[12.5px] text-muted-foreground">没有匹配的条目。</p>
          </template>
        </div>

        <!-- 右：版本列表 -->
        <aside class="w-60 shrink-0">
          <div class="mb-1.5 text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">版本</div>
          <div class="space-y-0.5">
            <button
              v-for="e in entries"
              :key="e.version"
              type="button"
              class="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[12.5px] transition-colors"
              :class="e.version === selected ? 'bg-[var(--shell-accent-tint)] font-semibold text-primary' : 'text-foreground/80 hover:bg-[var(--shell-accent-wash)]'"
              @click="selectVersion(e.version)"
            >
              <span class="font-mono tabular-nums">{{ e.version }}</span>
              <span
                v-if="e.version === current"
                class="ml-auto shrink-0 rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary"
              >你在使用</span>
              <span
                v-else-if="isNewer(e.version, current)"
                class="ml-auto shrink-0 rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-600"
              >可更新</span>
            </button>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
