<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'
import { useRouter } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type MissingItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 缺失资源：列出零字节 / 无法解析 / 缺封面的成品文件，并说明每条的原因。
 *
 * 判定在服务端（core/library.py 的 probe_epub）：真实解开 EPUB 容器读 OPF，
 * 所以「无法解析」「缺封面」都不是猜测。
 */
const ui = useUiStore()
const router = useRouter()

const ISSUE_META: Record<string, { label: string; tone: 'warn' | 'err'; hint: string }> = {
  'zero-bytes': {
    label: '零字节',
    tone: 'err',
    hint: '文件大小为 0，通常是写入中断 —— 需要重新生成一份。',
  },
  unparsable: {
    label: '无法解析',
    tone: 'err',
    hint: '不是有效的 EPUB 容器（解不开 zip 或找不到 OPF），书名与目录都读不出来。',
  },
  'no-cover': {
    label: '缺封面',
    tone: 'warn',
    hint: 'EPUB 里没有引用任何封面图，书架与阅读器里会显示空白占位。',
  },
}

const items = ref<MissingItem[]>([])
const total = ref(0)
const loading = ref(true)
const filter = ref('')

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(2)} MB`
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

function meta(issue: string) {
  return ISSUE_META[issue] ?? { label: issue, tone: 'warn' as const, hint: '' }
}

const counts = computed(() => {
  const out: Record<string, number> = {}
  for (const it of items.value) {
    for (const i of it.issues) out[i] = (out[i] ?? 0) + 1
  }
  return out
})

const issueKeys = computed(() => Object.keys(counts.value))

const filtered = computed(() =>
  filter.value ? items.value.filter((i) => i.issues.includes(filter.value)) : items.value,
)

function countOf(key: string): number {
  return key ? (counts.value[key] ?? 0) : items.value.length
}

function load(): void {
  loading.value = true
  api
    .missing()
    .then((r) => {
      items.value = r.items ?? []
      total.value = r.total ?? 0
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，刷新挂 onActivated（首次挂载也会触发）
onActivated(load)

/** 「重新转换」落到本地转换页 —— 那里才能真的重新生成成品 */
function goConvert(): void {
  router.push({ name: 'tools-local' })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="filter === '' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'"
        @click="filter = ''"
      >
        全部 <span class="ml-1 tabular-nums opacity-70">{{ countOf('') }}</span>
      </button>
      <button
        v-for="k in issueKeys"
        :key="k"
        type="button"
        class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="filter === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'"
        @click="filter = k"
      >
        {{ meta(k).label }} <span class="ml-1 tabular-nums opacity-70">{{ countOf(k) }}</span>
      </button>

      <Button class="ml-auto" :disabled="loading" @click="load">重新扫描</Button>
      <span class="text-[11.5px] text-muted-foreground">共扫描 {{ total }} 本书目</span>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <Card v-else-if="filtered.length" padding="none">
      <div
        v-for="it in filtered"
        :key="it.name"
        class="flex items-start gap-3 border-b border-border/60 px-4 py-3 last:border-b-0"
      >
        <span class="grid h-8 w-8 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
          <Icon name="alert" class="h-4 w-4" />
        </span>

        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="min-w-0 truncate text-[12.5px] font-medium text-foreground" :title="it.name">
              {{ it.name }}
            </span>
            <Badge v-for="iss in it.issues" :key="iss" :tone="meta(iss).tone">{{ meta(iss).label }}</Badge>
          </div>
          <div class="mt-0.5 text-[11px] text-muted-foreground tabular-nums">
            {{ fmtSize(it.size) }} · {{ fmtTime(it.mtime) }}
          </div>
          <ul class="mt-1.5 flex flex-col gap-0.5">
            <li v-for="iss in it.issues" :key="iss" class="text-[11.5px] leading-relaxed text-muted-foreground">
              · {{ meta(iss).hint }}
            </li>
          </ul>
        </div>

        <Button size="sm" class="shrink-0" @click="goConvert">重新转换</Button>
      </div>
    </Card>

    <EmptyState
      v-else
      icon="check"
      title="没有发现缺失资源"
      desc="所有成品文件都能正常解析、有封面、且不是空文件 —— 这正是期望的状态。"
    >
      <template #action>
        <Button @click="goConvert">去本地转换</Button>
      </template>
    </EmptyState>
  </div>
</template>
