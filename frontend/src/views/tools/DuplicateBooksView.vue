<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type DuplicateGroup } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 重复书籍：按「归一化书名 + 归一化作者」分组，每组保留一项、其余移入回收目录。
 *
 * **不会真删**：清理动作走 POST /api/duplicates/resolve，后端把文件 move 进
 * CACHE_DIR/recycle，响应里带回回收目录路径，方便随时人工找回。
 */
const ui = useUiStore()

const groups = ref<DuplicateGroup[]>([])
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
/** 每组保留哪一项（组 key → 文件名） */
const keep = ref<Record<string, string>>({})
const lastRecycleDir = ref('')

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(2)} MB`
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** 默认保留体积最大的一项（通常内容最完整） */
function defaultKeep(g: DuplicateGroup): string {
  const sorted = [...g.items].sort((a, b) => b.size - a.size)
  return sorted[0]?.name ?? ''
}

function keepOf(g: DuplicateGroup): string {
  return keep.value[g.key] ?? defaultKeep(g)
}

function setKeep(key: string, name: string): void {
  keep.value[key] = name
}

function removeOf(g: DuplicateGroup): string[] {
  const k = keepOf(g)
  return g.items.filter((i) => i.name !== k).map((i) => i.name)
}

const pending = computed(() => groups.value.reduce((n, g) => n + removeOf(g).length, 0))

function load(): void {
  loading.value = true
  api
    .duplicates()
    .then((r) => {
      groups.value = r.groups ?? []
      total.value = r.total ?? 0
      // 重新扫描后重建保留项：**保留用户已选的**（只要那个文件还在这组里），
      // 否则回落到默认 —— 否则每次切回标签都会把用户的选择重置掉。
      const next: Record<string, string> = {}
      for (const g of groups.value) {
        const prev = keep.value[g.key]
        next[g.key] = prev && g.items.some((i) => i.name === prev) ? prev : defaultKeep(g)
      }
      keep.value = next
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，刷新挂 onActivated（首次挂载也会触发）
onActivated(load)

function apply(): void {
  const jobs = groups.value
    .map((g) => ({ keep: keepOf(g), remove: removeOf(g) }))
    .filter((j) => j.remove.length)
  if (!jobs.length) {
    ui.toast('没有需要清理的条目')
    return
  }

  busy.value = true
  Promise.all(jobs.map((j) => api.duplicatesResolve(j.keep, j.remove)))
    .then((rs) => {
      const moved = rs.reduce((n, r) => n + r.moved.length, 0)
      const failed = rs.reduce((n, r) => n + r.errors.length, 0)
      lastRecycleDir.value = rs[0]?.recycle_dir ?? ''
      ui.toast(`已移入回收目录 ${moved} 个${failed ? `，${failed} 个失败` : ''}`)
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-2">
      <Button :disabled="loading" @click="load">重新扫描</Button>
      <span class="text-[11.5px] text-muted-foreground">
        共扫描 {{ total }} 本书目，发现 {{ groups.length }} 组重复
      </span>
    </div>

    <p v-if="lastRecycleDir" class="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
      <Icon name="check" class="h-3.5 w-3.5 text-success" />
      上次清理的文件在回收目录：<span class="font-mono text-foreground">{{ lastRecycleDir }}</span>（不会自动删除，可随时取回）
    </p>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <template v-else-if="groups.length">
      <Card v-for="g in groups" :key="g.key" padding="none">
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <h3 class="min-w-0 truncate text-[13px] font-semibold text-foreground" :title="g.title">
            {{ g.title || '（无书名）' }}
          </h3>
          <span class="truncate text-[11.5px] text-muted-foreground">{{ g.author }}</span>
          <Badge class="ml-auto">{{ g.items.length }} 份</Badge>
        </div>

        <p class="border-b border-border/60 bg-muted/40 px-4 py-2 text-[11.5px] text-muted-foreground">
          判定依据：{{ g.reason }}
        </p>

        <div
          v-for="it in g.items"
          :key="it.name"
          class="flex items-center gap-2.5 border-b border-border/60 px-4 py-2.5 last:border-b-0"
        >
          <input
            type="radio"
            :name="`keep-${g.key}`"
            class="h-3.5 w-3.5 shrink-0 accent-[var(--primary)]"
            :checked="keepOf(g) === it.name"
            :aria-label="`保留 ${it.name}`"
            @change="setKeep(g.key, it.name)"
          >
          <div class="min-w-0 flex-1">
            <div class="truncate text-[12.5px] text-foreground" :title="it.name">{{ it.name }}</div>
            <div class="text-[11px] text-muted-foreground tabular-nums">
              {{ fmtSize(it.size) }} · {{ fmtTime(it.mtime) }}
            </div>
          </div>
          <Badge v-if="keepOf(g) === it.name" tone="ok">保留</Badge>
          <Badge v-else tone="warn">将清理</Badge>
        </div>
      </Card>

      <div class="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-4 py-3">
        <span class="text-[11.5px] text-muted-foreground">
          将把 <span class="font-semibold text-foreground tabular-nums">{{ pending }}</span> 个文件移入回收目录
        </span>
        <Button variant="primary" class="ml-auto" :disabled="busy || !pending" @click="apply">
          执行清理
        </Button>
      </div>
    </template>

    <EmptyState
      v-else
      icon="layers"
      title="没有发现重复书籍"
      desc="判定口径是「归一化后的书名与作者相同」——标点、空格与「校对版全本」这类版本后缀都会被忽略。"
    />
  </div>
</template>
