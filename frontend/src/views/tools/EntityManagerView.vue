<script setup lang="ts">
import { computed, onActivated, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import Segment from '@/components/ui/Segment.vue'
import { api, type EntityItem, type EntityKind, type RenamePlan } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 实体管理：按作者 / 系列聚合成品书目，可重命名、可合并。
 *
 * 数据源是扫描 output/ 的成品文件（后端没有图书库实体）。改名实质是批量重命名文件，
 * 同时会同步改写 EPUB 内部的 dc:creator / calibre:series 元数据，让工具页聚合能识别新名称。
 * 任何改动都走「先预览、再应用」——预览由服务端算，应用只回传预览过的条目。
 */
const ui = useUiStore()

const KINDS = [
  { value: 'author', label: '作者' },
  { value: 'series', label: '系列' },
]

const kind = ref<EntityKind>('author')
const items = ref<EntityItem[]>([])
const total = ref(0)
const loading = ref(true)
const keyword = ref('')

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

function load(): void {
  loading.value = true
  api
    .entities(kind.value)
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

watch(kind, () => {
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
      ? api.entityRenamePreview(kind.value, ed.name, target)
      : api.entityMerge(kind.value, ed.name, target)
  call
    .then((r) => {
      plan.value = r
      if (!r.items.length) {
        ui.toast('这个名称没有出现在任何文件名里，改不到')
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
  api
    .entityRenameApply(kind.value, editing.value.target.trim(), clean)
    .then((r) => {
      const failed = r.errors.length
      ui.toast(`已改名 ${r.count ?? 0} 个文件${failed ? `，${failed} 个失败` : ''}`)
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

    <Card v-else-if="filtered.length" padding="none">
      <div v-for="it in filtered" :key="it.name" class="border-b border-border last:border-b-0">
        <div class="flex items-center gap-2.5 px-4 py-3">
          <Icon :name="kind === 'author' ? 'users' : 'layers'" class="h-4 w-4 text-muted-foreground" />
          <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">{{ it.name }}</span>
          <Badge>{{ it.count }} 本</Badge>
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

          <div v-if="plan" class="mt-3">
            <p class="mb-2 text-[11.5px] text-muted-foreground">
              命中 {{ plan.items.length }} 个文件 · 可提交 {{ cleanCount }} 个<template v-if="conflictCount">，{{ conflictCount }} 个冲突已置灰</template>
            </p>

            <div v-if="plan.items.length" class="max-h-64 overflow-y-auto rounded-md border border-border bg-card">
              <div
                v-for="p in plan.items"
                :key="p.old"
                class="flex flex-col gap-0.5 border-b border-border/60 px-3 py-2 last:border-b-0"
                :class="p.conflict ? 'opacity-55' : ''"
              >
                <div class="flex items-center gap-2 text-[12px]">
                  <span class="min-w-0 flex-1 truncate text-muted-foreground" :title="p.old">{{ p.old }}</span>
                  <Icon name="arrowRight" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span
                    class="min-w-0 flex-1 truncate font-medium"
                    :class="p.conflict ? 'text-destructive' : 'text-foreground'"
                    :title="p.new"
                  >
                    {{ p.new }}
                  </span>
                </div>
                <div v-if="p.conflict" class="text-[11px] text-destructive">冲突：{{ p.reason }}</div>
              </div>
            </div>

            <p v-else class="text-[11.5px] leading-relaxed text-muted-foreground">
              没有命中任何文件。改名会同步更新文件与 EPUB 内部元数据（作者 / 系列），
              但该名称在当前成品里没有出现，所以改不到。
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
