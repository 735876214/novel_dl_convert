<script setup lang="ts">
import { computed, onActivated, ref, watch } from 'vue'

import LibraryScopeSwitch from '@/components/tools/LibraryScopeSwitch.vue'
import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { useLibraryNames } from '@/composables/useLibraryNames'
import { api, type DuplicateGroup, type DuplicateItem } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 重复书籍：**同作者（归一化后一致）+ 书名相似度 ≥ 阈值** 分组。
 * 阈值默认 85%（同 Calibre 的 Similar-title threshold），可调低抓近似、调高只留全同。
 *
 * **不会真删**：清理动作走 POST /api/duplicates/resolve，后端把文件 move 进
 * CACHE_DIR/recycle，响应里带回回收目录路径，方便随时人工找回。
 *
 * 范围（第 13 期）：全部书库时会把**跨库重复**单独成段展示 —— 同名书分散在不同库时
 * 往往同时撞 ``book_id``，是「进度张冠李戴」冲突的高发区，最该先处理。
 */
const ui = useUiStore()
const library = useLibraryStore()
const { nameOf } = useLibraryNames()

const groups = ref<DuplicateGroup[]>([])
const total = ref(0)
const loading = ref(true)
const busy = ref(false)
/** 加载失败信息：失败不能退化成「没有发现重复书籍」。 */
const error = ref('')
/** 书名相似度阈值（%）。变更后重新扫描 —— 分组结果由它决定 */
const threshold = ref(85)
const THRESHOLD_PRESETS = [70, 85, 95] as const
/** 书库范围（第 13 期）：空串 = 全部书库 */
const libScope = ref('')
/** 每组保留哪一项（组 key → **条目键**，见 itemKey） */
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

/**
 * 组内条目的唯一键。**不能只用文件名**：不同库可以有同名文件
 * （跨库重复正是本期要处理的对象），只用名字会让「保留项 / 清理项」串库。
 */
function itemKey(it: DuplicateItem): string {
  return `${it.library_id || ''}|${it.name}`
}

/** 默认保留体积最大的一项（通常内容最完整） */
function defaultKeep(g: DuplicateGroup): string {
  const sorted = [...g.items].sort((a, b) => b.size - a.size)
  return sorted[0] ? itemKey(sorted[0]) : ''
}

function keepOf(g: DuplicateGroup): string {
  return keep.value[g.key] ?? defaultKeep(g)
}

/** 被保留的那一项（清理日志里记它的名字） */
function keepItem(g: DuplicateGroup): DuplicateItem | null {
  const k = keepOf(g)
  return g.items.find((i) => itemKey(i) === k) ?? null
}

function setKeep(key: string, it: DuplicateItem): void {
  keep.value[key] = itemKey(it)
}

/** 待清理项带 **library_id**：同名文件分属不同库时，只给名字后端会移错库的文件 */
function removeOf(g: DuplicateGroup): Array<{ name: string; library_id?: string | null }> {
  const k = keepOf(g)
  return g.items
    .filter((i) => itemKey(i) !== k)
    .map((i) => ({ name: i.name, library_id: i.library_id }))
}

const pending = computed(() => groups.value.reduce((n, g) => n + removeOf(g).length, 0))

/**
 * 展示分组。全部书库时把**跨库重复**单独成段 —— 它们和库内重复的处理心态不同：
 * 库内重复是「留哪一本」，跨库重复还牵扯 book_id 冲突，要先看清归属再动手。
 */
const sections = computed<Array<{ label: string; hint: string; items: DuplicateGroup[] }>>(() => {
  if (libScope.value) return [{ label: '', hint: '', items: groups.value }]
  const cross = groups.value.filter((g) => g.cross_library)
  const plain = groups.value.filter((g) => !g.cross_library)
  const out: Array<{ label: string; hint: string; items: DuplicateGroup[] }> = []
  if (cross.length) {
    out.push({
      label: '跨库重复',
      hint: '同名书分散在不同书库，容易同时撞 book_id（进度张冠李戴），建议先处理',
      items: cross,
    })
  }
  if (plain.length) out.push({ label: cross.length ? '库内重复' : '', hint: '', items: plain })
  return out
})

function load(): void {
  loading.value = true
  error.value = ''
  // 侧栏已拉过；这里防的是直接刷新进工具页时 store 仍为空（内部会早退）
  void library.loadLibraries()
  api
    .duplicates(threshold.value, libScope.value)
    .then((r) => {
      groups.value = r.groups ?? []
      total.value = r.total ?? 0
      // 重新扫描后重建保留项：**保留用户已选的**（只要那一项还在这组里），
      // 否则回落到默认 —— 否则每次切回标签都会把用户的选择重置掉。
      const next: Record<string, string> = {}
      for (const g of groups.value) {
        const prev = keep.value[g.key]
        next[g.key] = prev && g.items.some((i) => itemKey(i) === prev) ? prev : defaultKeep(g)
      }
      keep.value = next
    })
    .catch((e: Error) => {
      groups.value = []
      total.value = 0
      error.value = e.message
    })
    .finally(() => {
      loading.value = false
    })
}

/** 改阈值后重扫。换阈值等于换判定口径，用户已选的保留项可能已不在组里，交给 load 兜底 */
function setThreshold(v: number): void {
  if (threshold.value === v) return
  threshold.value = v
  load()
}

// 换范围 = 换判定集合，保留项按组 key 复用（组不在了自然回落），但必须重扫
watch(libScope, load)

// 工具页子页在 KeepAlive 下不会重新挂载，刷新挂 onActivated（首次挂载也会触发）
onActivated(load)

function apply(): void {
  const jobs = groups.value
    .map((g) => ({ keep: keepItem(g)?.name ?? '', remove: removeOf(g) }))
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

      <span class="ml-1 text-[11.5px] text-muted-foreground">相似度阈值</span>
      <div class="flex gap-1">
        <button
          v-for="p in THRESHOLD_PRESETS"
          :key="p"
          type="button"
          class="cursor-pointer rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors"
          :class="threshold === p
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground hover:text-foreground'"
          @click="setThreshold(p)"
        >
          {{ p }}%
        </button>
      </div>

      <LibraryScopeSwitch v-model="libScope" />

      <span class="text-[11.5px] text-muted-foreground">
        共扫描 {{ total }} 本书目，发现 {{ groups.length }} 组重复
      </span>
    </div>

    <p class="text-[11.5px] text-muted-foreground">
      判定口径：<span class="text-foreground">同作者</span>（归一化后一致为前提）+
      书名相似度 ≥ {{ threshold }}%。前提之外只看书名，标点、空格与「校对版全本」这类版本后缀都会先被忽略。
    </p>

    <p v-if="lastRecycleDir" class="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
      <Icon name="check" class="h-3.5 w-3.5 text-success" />
      上次清理的文件在回收目录：<span class="font-mono text-foreground">{{ lastRecycleDir }}</span>（不会自动删除，可随时取回）
    </p>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <!-- 加载失败：可重试的错误态（不与「没有发现重复书籍」空态混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>重复书籍加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

    <template v-else-if="groups.length">
      <template v-for="s in sections" :key="s.label || 'all'">
        <div v-if="s.label" class="flex flex-col gap-0.5">
          <h3 class="text-[12.5px] font-semibold text-foreground">{{ s.label }}</h3>
          <p v-if="s.hint" class="text-[11.5px] text-muted-foreground">{{ s.hint }}</p>
        </div>

        <Card v-for="g in s.items" :key="g.key" padding="none">
          <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
            <h3 class="min-w-0 truncate text-[13px] font-semibold text-foreground" :title="g.title">
              {{ g.title || '（无书名）' }}
            </h3>
            <span class="truncate text-[11.5px] text-muted-foreground">{{ g.author }}</span>
            <Badge v-if="g.cross_library" tone="accent">跨库重复</Badge>
            <Badge class="ml-auto">{{ g.items.length }} 份</Badge>
          </div>

          <p class="border-b border-border/60 bg-muted/40 px-4 py-2 text-[11.5px] text-muted-foreground">
            判定依据：{{ g.reason }}
            <span v-if="g.similarity < 100" class="tabular-nums">（组内最低相似度 {{ g.similarity }}%）</span>
          </p>

          <div
            v-for="it in g.items"
            :key="itemKey(it)"
            class="flex items-center gap-2.5 border-b border-border/60 px-4 py-2.5 last:border-b-0"
          >
            <input
              type="radio"
              :name="`keep-${g.key}`"
              class="h-3.5 w-3.5 shrink-0 accent-[var(--primary)]"
              :checked="keepOf(g) === itemKey(it)"
              :aria-label="`保留 ${it.name}`"
              @change="setKeep(g.key, it)"
            >
            <div class="min-w-0 flex-1">
              <div class="truncate text-[12.5px] text-foreground" :title="it.name">{{ it.name }}</div>
              <div class="text-[11px] text-muted-foreground tabular-nums">
                {{ fmtSize(it.size) }} · {{ fmtTime(it.mtime) }}
              </div>
            </div>
            <Badge v-if="!libScope && it.library_id" class="shrink-0">{{ nameOf(it.library_id) }}</Badge>
            <Badge v-if="keepOf(g) === itemKey(it)" tone="ok">保留</Badge>
            <Badge v-else tone="warn">将清理</Badge>
          </div>
        </Card>
      </template>

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
      :desc="`当前阈值下（同作者 + 书名相似度 ≥ ${threshold}%）没有成组的书。调低阈值可以抓出「同名近似」的版本，比如加了「第二版」后缀的那类。`"
    />
  </div>
</template>
