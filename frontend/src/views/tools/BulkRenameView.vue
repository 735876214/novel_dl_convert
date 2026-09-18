<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import LibraryScopeSwitch from '@/components/tools/LibraryScopeSwitch.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import Badge from '@/components/ui/Badge.vue'
import { useLibraryNames } from '@/composables/useLibraryNames'
import { api, type RenameItem, type RenamePlan } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 批量重命名：按规则生成「旧名 → 新名」对照表，确认后才落盘。
 *
 * 规则由**服务端**解释（POST /api/rename/preview），前端只负责展示与勾选；
 * 应用时回传的是预览过的具体条目，而不是规则 —— 避免同一套规则在两端解释不一致。
 *
 * 默认规则来自服务端「设置 → 文件命名」（config.naming）；取不到时退回内置默认，
 * 保证后端不可达时工具页仍可用。
 */
const ui = useUiStore()

const PATTERN_FIELDS = ['{title}', '{author}', '{series}', '{index}', '{ext}']

/** 内置兜底（与后端 config.DEFAULTS.naming.pattern 保持一致） */
const DEFAULT_PATTERN = '{author} - {title}'

const pattern = ref(DEFAULT_PATTERN)
/** 格式筛选（不是书库范围！书库范围是 libScope） */
const scope = ref('all')
/** 书库范围（第 13 期）：空串 = 全部书库 */
const libScope = ref('')
const plan = ref<RenamePlan | null>(null)
const checked = ref<Record<string, boolean>>({})
const busy = ref(false)

const { nameOf } = useLibraryNames()

/**
 * 勾选表的键。**不能用文件名单独当键**：不同库可以有同名文件，
 * 那样勾一个会连带勾上另一个库的同名条目（第 13 期多库下真实存在）。
 */
function keyOf(it: RenameItem | { old: string; library_id?: string | null }): string {
  return `${it.library_id || ''}|${it.old}`
}

const conflictCount = computed(() => (plan.value?.items ?? []).filter((i) => i.conflict).length)
const selected = computed(() =>
  (plan.value?.items ?? []).filter((i) => !i.conflict && checked.value[keyOf(i)]),
)
const selectedCount = computed(() => selected.value.length)
const selectableCount = computed(() => (plan.value?.items ?? []).filter((i) => !i.conflict).length)

const fields = computed(() => plan.value?.fields ?? PATTERN_FIELDS)

function reset(): void {
  plan.value = null
  checked.value = {}
}

// 不挂 onActivated 重置：本页在 KeepAlive 下切换标签要保留「规则 + 预览表 + 勾选」
// （需求明确要求切换不重置）。预览结果即使过期也不会改错文件 ——
// 后端 apply 会逐条重新校验存在性与冲突，失效条目只会报错跳过。

function makePreview(): void {
  if (!pattern.value.trim()) {
    ui.toast('请先填写重命名规则')
    return
  }
  busy.value = true
  api
    .renamePreview(scope.value, pattern.value, libScope.value)
    .then((r) => {
      plan.value = r
      // 默认勾选所有不冲突的条目
      const next: Record<string, boolean> = {}
      for (const it of r.items) next[keyOf(it)] = !it.conflict
      checked.value = next
      if (!r.items.length) ui.toast('没有匹配的文件')
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function toggleOne(key: string): void {
  checked.value[key] = !checked.value[key]
}

function toggleAll(): void {
  const wantAll = selectedCount.value < selectableCount.value
  const next: Record<string, boolean> = {}
  for (const it of plan.value?.items ?? []) next[keyOf(it)] = !it.conflict && wantAll
  checked.value = next
}

function apply(): void {
  const items = selected.value
  if (!items.length) {
    ui.toast('还没有勾选任何条目')
    return
  }
  busy.value = true
  api
    .renameApply(items)
    .then((r) => {
      const failed = r.errors.length
      ui.toast(`已改名 ${r.count ?? 0} 个文件${failed ? `，${failed} 个失败` : ''}`)
      reset()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

onMounted(async () => {
  try {
    const r = await api.getConfig()
    const naming = r.config.naming
    if (naming?.pattern) pattern.value = naming.pattern
    if (naming?.scope) scope.value = naming.scope
  } catch {
    /* 后端不可达时保持内置默认，工具页仍可用 */
  }
})

// 换范围后旧预览里的条目已经不属于当前范围，整张表作废重来（规则文本保留）
watch(libScope, reset)
</script>

<template>
  <div class="flex flex-col gap-4">
    <Card>
      <h3 class="text-[13px] font-semibold text-foreground">重命名规则</h3>
      <p class="mt-1 mb-2.5 text-[11.5px] leading-relaxed text-muted-foreground">
        可用占位符：
        <span v-for="(f, i) in fields" :key="f" class="font-mono text-foreground">
          {{ f }}<span v-if="i < fields.length - 1">、</span>
        </span>
        （扩展名会自动保留在末尾）
      </p>
      <p class="mb-2.5 text-[11px] text-muted-foreground">
        初始规则来自
        <RouterLink to="/settings/library/file-naming" class="underline">设置 → 文件命名</RouterLink>；
        在此处修改不会回写设置。范围切到某个库时仍用上面这条规则，
        库自己的命名规则在「书库管理 → 设置」里改。
      </p>

      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="pattern"
          type="text"
          placeholder="{index}. {author} - {title}"
          aria-label="重命名规则"
          class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-3 font-mono text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          @keydown.enter="makePreview"
        >
        <select
          v-model="scope"
          aria-label="格式筛选"
          class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
        >
          <option value="all">全部格式</option>
          <option value="epub">仅 EPUB</option>
          <option value="mobi">仅 MOBI</option>
          <option value="azw3">仅 AZW3</option>
          <option value="pdf">仅 PDF</option>
          <option value="txt">仅 TXT</option>
        </select>
        <LibraryScopeSwitch v-model="libScope" />
        <Button variant="primary" :disabled="busy" @click="makePreview">生成预览</Button>
      </div>
    </Card>

    <Card v-if="plan && plan.items.length" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">改名预览</h3>
        <span class="text-[11.5px] text-muted-foreground">
          共 {{ plan.items.length }} 项<template v-if="conflictCount">，{{ conflictCount }} 项冲突不可提交</template>
        </span>
        <Button size="sm" variant="ghost" class="ml-auto" @click="toggleAll">全选 / 全不选</Button>
      </div>

      <div class="max-h-[26rem] overflow-y-auto">
        <div
          v-for="p in plan.items"
          :key="keyOf(p)"
          class="flex items-start gap-2.5 border-b border-border/60 px-4 py-2.5 last:border-b-0"
          :class="p.conflict ? 'opacity-55' : ''"
        >
          <input
            type="checkbox"
            class="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[var(--primary)]"
            :checked="!!checked[keyOf(p)]"
            :disabled="p.conflict"
            :aria-label="`选择 ${p.old}`"
            @change="toggleOne(keyOf(p))"
          >
          <div class="flex min-w-0 flex-1 flex-col gap-0.5">
            <div class="flex items-center gap-2 text-[12px]">
              <span class="min-w-0 flex-1 truncate text-muted-foreground" :title="p.old">{{ p.old }}</span>
              <Badge v-if="!libScope && p.library_id" class="shrink-0">{{ nameOf(p.library_id) }}</Badge>
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
      </div>

      <div class="flex items-center gap-2 border-t border-border px-4 py-3">
        <span class="text-[11.5px] text-muted-foreground">
          将改名 <span class="font-semibold text-foreground tabular-nums">{{ selectedCount }}</span> 个文件
        </span>
        <Button variant="primary" class="ml-auto" :disabled="busy || !selectedCount" @click="apply">
          应用
        </Button>
      </div>
    </Card>

    <EmptyState
      v-else-if="plan"
      icon="pencil"
      title="没有匹配的文件"
      desc="换个规则，或把格式筛选切回「全部格式」。"
    />

    <Card v-else class="py-10 text-center text-[12.5px] text-muted-foreground">
      填一条规则后点「生成预览」，会先列出「旧名 → 新名」对照表，由你确认后才真正落盘。
    </Card>
  </div>
</template>
