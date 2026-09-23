<script setup lang="ts">
import { computed, onActivated, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import Segment from '@/components/ui/Segment.vue'
import LibraryScopeSwitch from '@/components/tools/LibraryScopeSwitch.vue'
import { useLibraryNames } from '@/composables/useLibraryNames'
import { api, type EntityItem, type EntityKind, type RenamePlan } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 实体管理：按作者 / 系列聚合成品书目，可重命名、可合并。
 *
 * 数据源是扫描各库的书目（后端没有图书库实体）。第 28 期起改名是**纯元数据操作**：
 * 只写服务端元数据覆盖（author / series），源文件名与文件内容都不动 ——
 * 书目的 `book_id` 由文件名派生，所以关联数据（进度 / 批注 / 评分）也不会断链。
 * 想让**副本**名跟着变，去「转换日志 → 刮削 → 命名规则」按规则重出版（那条路只改副本名）。
 *
 * 任何改动都走「先预览、再应用」——预览由服务端算；应用只回传 `{type, from, to}`
 * 与预览时一致的名称，**要改哪些书由服务端自己算**（预览过期也改不错）。
 */
const ui = useUiStore()
const library = useLibraryStore()
const { nameOf } = useLibraryNames()

const KINDS = [
  { value: 'author', label: '作者' },
  { value: 'series', label: '系列' },
]

const kind = ref<EntityKind>('author')
const items = ref<EntityItem[]>([])
const total = ref(0)
const loading = ref(true)
const keyword = ref('')
/** 加载失败信息：失败不能退化成「还没有可管理的实体」。 */
const error = ref('')
/** 统计范围（第 13 期）：**空串 = 全部书库**，等于加库维度之前的行为 */
const scope = ref('')

/** 展开的行。始终是对象（name 为空表示没展开），避免模板里判空 */
const editing = ref<{ name: string; mode: 'rename' | 'merge'; target: string }>({
  name: '',
  mode: 'rename',
  target: '',
})
const plan = ref<RenamePlan | null>(null)
const busy = ref(false)

const filtered = computed(() => {
  const k = keyword.value.trim().toLowerCase()
  if (!k) return items.value
  return items.value.filter((i) => i.name.toLowerCase().includes(k))
})

const cleanCount = computed(() => (plan.value?.items ?? []).filter((i) => !i.conflict).length)
const conflictCount = computed(() => (plan.value?.items ?? []).filter((i) => i.conflict).length)
const noun = computed(() => (kind.value === 'author' ? '作者' : '系列'))

/** 书名 → 所属库（判断一个作者 / 系列是否横跨多个库） */
const libraryOfBook = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const b of library.books) out[b.name] = String(b.library_id || '')
  return out
})

/**
 * 横跨 ≥2 个库的实体名 → 库数。
 * 被拆到多个库的同名作者 / 系列是最该被重新归类的情况，所以在列表上直接标出来。
 */
const spreadLibraries = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const it of filtered.value) {
    const seen = new Set<string>()
    for (const n of it.books) seen.add(libraryOfBook.value[n] ?? '')
    if (seen.size > 1) out[it.name] = seen.size
  }
  return out
})

function load(): void {
  loading.value = true
  error.value = ''
  // 侧栏已拉过；这里防的是「直接刷新进工具页」时 store 仍为空（内部会早退，不产生额外请求）
  void library.loadLibraries()
  void library.loadBooks()
  api
    .entities(kind.value, scope.value)
    .then((r) => {
      items.value = r.items ?? []
      total.value = r.total ?? 0
    })
    .catch((e: Error) => {
      items.value = []
      total.value = 0
      error.value = e.message
    })
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，刷新挂 onActivated（首次挂载也会触发）
onActivated(load)

watch(kind, () => {
  closeEditor()
  load()
})

// 换范围 = 换数据集，之前那份预览不再成立
watch(scope, () => {
  closeEditor()
  load()
})

function closeEditor(): void {
  editing.value = { name: '', mode: 'rename', target: '' }
  plan.value = null
}

function openEditor(item: EntityItem, mode: 'rename' | 'merge'): void {
  editing.value = { name: item.name, mode, target: '' }
  plan.value = null
}

function makePreview(): void {
  const ed = editing.value
  const target = ed.target.trim()
  if (!target) {
    ui.toast(ed.mode === 'rename' ? '请先填写新名称' : '请先填写要合并到的目标名称')
    return
  }
  busy.value = true
  const call =
    ed.mode === 'rename'
      ? api.entityRenamePreview(kind.value, ed.name, target, scope.value)
      : api.entityMerge(kind.value, ed.name, target, scope.value)
  call
    .then((r) => {
      plan.value = r
      if (!r.items.length) {
        ui.toast('没有书的该字段等于这个名字，改不到')
      }
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function applyPlan(): void {
  const clean = (plan.value?.items ?? []).filter((i) => !i.conflict)
  if (!clean.length) {
    ui.toast('没有可提交的条目')
    return
  }
  busy.value = true
  // 只回传「把哪个名字改成哪个名字」：要改哪些书由服务端按 from 重算，
  // 所以即使这份预览已经过期，也不会改到别的书上（更不会动文件）。
  api
    .entityRenameApply(kind.value, editing.value.name, editing.value.target.trim(), scope.value)
    .then((r) => {
      const failed = r.errors.length
      ui.toast(`已更新 ${r.count ?? 0} 本书的元数据${failed ? `，${failed} 本失败` : ''}`)
      closeEditor()
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
      <Segment v-model="kind" :options="KINDS" />
      <LibraryScopeSwitch v-model="scope" />
      <input
        v-model="keyword"
        type="text"
        :placeholder="`按${noun}名筛选…`"
        :aria-label="`筛选${noun}`"
        class="h-8 w-56 rounded-md border border-border bg-muted px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
      >
      <Button :disabled="loading" @click="load">刷新</Button>
      <span class="text-[11.5px] text-muted-foreground">
        {{ filtered.length }} / {{ items.length }} 个{{ noun }} · 共 {{ total }} 本书目
      </span>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <!-- 加载失败：可重试的错误态（不与空态混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>实体加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

    <Card v-else-if="filtered.length" padding="none">
      <div v-for="it in filtered" :key="it.name" class="border-b border-border last:border-b-0">
        <div class="flex items-center gap-2.5 px-4 py-3">
          <Icon :name="kind === 'author' ? 'users' : 'layers'" class="h-4 w-4 text-muted-foreground" />
          <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">{{ it.name }}</span>
          <Badge>{{ it.count }} 本</Badge>
          <Badge v-if="spreadLibraries[it.name]" tone="accent">跨 {{ spreadLibraries[it.name] }} 个库</Badge>
          <Button size="sm" variant="ghost" :disabled="busy" @click="openEditor(it, 'rename')">重命名</Button>
          <Button size="sm" variant="ghost" :disabled="busy" @click="openEditor(it, 'merge')">合并</Button>
        </div>

        <div v-if="editing.name === it.name" class="border-t border-border/60 bg-muted/40 px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[11.5px] text-muted-foreground">
              {{ editing.mode === 'rename' ? '新名称' : '合并到' }}
            </span>
            <input
              v-model="editing.target"
              type="text"
              :placeholder="editing.mode === 'rename' ? '例如：远瞳' : '例如：爱潜水的乌贼'"
              :aria-label="editing.mode === 'rename' ? '新名称' : '目标名称'"
              class="h-8 min-w-0 flex-1 rounded-md border border-border bg-card px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
              @keydown.enter="makePreview"
            >
            <Button variant="primary" :disabled="busy" @click="makePreview">生成预览</Button>
            <Button :disabled="busy" @click="closeEditor">取消</Button>
          </div>

          <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            改名只写服务端元数据（{{ noun }}），源文件名与文件内容都不变。
            要让<strong>副本</strong>名跟着变，去「转换日志 → 刮削 → 命名规则」按规则重出版。
          </p>

          <div v-if="plan" class="mt-3">
            <p class="mb-2 text-[11.5px] text-muted-foreground">
              命中 {{ plan.items.length }} 本书 · 可提交 {{ cleanCount }} 本<template v-if="conflictCount">，{{ conflictCount }} 项冲突已置灰</template>
            </p>

            <div v-if="plan.items.length" class="max-h-64 overflow-y-auto rounded-md border border-border bg-card">
              <div
                v-for="p in plan.items"
                :key="(p.library_id || '') + p.old"
                class="flex flex-col gap-0.5 border-b border-border/60 px-3 py-2 last:border-b-0"
                :class="p.conflict ? 'opacity-55' : ''"
              >
                <div class="flex items-center gap-2 text-[12px]">
                  <span class="min-w-0 flex-1 truncate font-medium text-foreground" :title="p.title || p.old">
                    {{ p.title || p.old }}
                  </span>
                  <Badge v-if="p.library_id" class="shrink-0">{{ nameOf(p.library_id) }}</Badge>
                  <span class="shrink-0 font-mono text-[10.5px] text-muted-foreground" :title="`文件名不变：${p.old}`">
                    {{ p.old }}
                  </span>
                </div>
                <div v-if="p.conflict" class="text-[11px] text-destructive">冲突：{{ p.reason }}</div>
              </div>
            </div>

            <p v-else class="text-[11.5px] leading-relaxed text-muted-foreground">
              没有书的该字段等于这个名字。改名只写服务端元数据（作者 / 系列），
              不移动文件、不改文件内容 —— 所以「命中 0 本」就是当前范围里没有可改的书。
            </p>

            <div v-if="plan.items.length" class="mt-2.5 flex items-center gap-2">
              <Button variant="primary" :disabled="busy || !cleanCount" @click="applyPlan">
                应用改名（{{ cleanCount }} 个）
              </Button>
              <Button :disabled="busy" @click="closeEditor">放弃</Button>
            </div>
          </div>
        </div>
      </div>
    </Card>

    <EmptyState
      v-else
      :icon="kind === 'author' ? 'users' : 'layers'"
      :title="keyword ? '没有匹配的实体' : `还没有可管理的${noun}`"
      :desc="
        keyword
          ? '换个关键词，或清空筛选框看全部。'
          : '导出目录里出现成品文件后，这里会按 EPUB 元数据自动聚合出作者与系列。'
      "
    />
  </div>
</template>
