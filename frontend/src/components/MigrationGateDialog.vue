<script setup lang="ts">
/**
 * 首次「按格式归库」的**阻塞式确认**（第 10 期 D8）。
 *
 * 为什么必须阻塞：迁移会**真移文件**。若做成一个可以随手关掉的提示，
 * 用户很可能永远看不到它，而书库已经因为「没归库」而功能不全 —— 状态一半、
 * 又没有入口解释，比直接问一次更糟。
 *
 * 因此这里的交互是：先给逐条预览（多少本、去哪、有没有同名冲突），
 * 再让用户明确选「执行 / 暂不迁移 / 以后自动执行」。选过就不再打扰（后端记 state）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type MigrationPreview } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const router = useRouter()
const library = useLibraryStore()
const { cfg, setVal, saveSection } = useSettingsConfig()

const open = ref(false)
const preview = ref<MigrationPreview | null>(null)
const busy = ref('')
const result = ref('')
const specMode = ref<Record<string, string>>({})

/** 待迁移按目标类型分组计数（给用户一个「到底要搬什么」的概览） */
const byType = computed(() => {
  const out: Record<string, number> = {}
  for (const it of preview.value?.items ?? []) {
    if (it.status !== 'ready') continue
    out[it.target_label] = (out[it.target_label] ?? 0) + 1
  }
  return out
})

const autoMigrate = computed(() => cfg.value?.libraries?.auto_migrate === true)

async function load(): Promise<void> {
  try {
    const pv = await api.migrationPreview()
    preview.value = pv
    for (const s of pv.suggest_specs) specMode.value[s.id] ??= 'inplace'
    // 勾了「以后自动执行」→ 不再打扰，直接安静地把事做完
    if (pv.needs_confirm && pv.gate.auto_migrate) {
      await runMigration()
      return
    }
    open.value = Boolean(pv.needs_confirm)
  } catch {
    // 读不到就**不打扰**：迁移是增强流程，不该因为一次网络抖动把人堵在门口
    open.value = false
  }
}

onMounted(load)

async function createSuggested(): Promise<void> {
  const specs = preview.value?.suggest_specs ?? []
  if (!specs.length) return
  busy.value = 'create'
  try {
    for (const s of specs) {
      const mode = (specMode.value[s.id] ?? 'inplace') as 'inplace' | 'import'
      const loc = s[mode]
      await api.createLibrary({
        name: s.name,
        type: s.type,
        mode,
        root_path: loc.root_path,
        source_subdir: s.source_subdir,
      })
    }
    await library.loadLibraries(true)
    preview.value = await api.migrationPreview()
    ui.toast(`已创建 ${specs.length} 个书库`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = ''
  }
}

async function runMigration(): Promise<void> {
  busy.value = 'migrate'
  result.value = ''
  try {
    const planned = await api.migrationPlan()
    if (!planned.batch_id) {
      result.value = planned.message || '没有可迁移的书'
      return
    }
    const res = await api.migrationApply(planned.batch_id)
    result.value = `已迁移 ${res.moved ?? 0} 本${res.failed ? `，失败 ${res.failed} 本` : ''}`
    ui.toast(result.value)
    await library.loadBooks(true)
    await library.loadLibraries(true)
    preview.value = await api.migrationPreview()
    // 有失败项就先别关：用户需要看到原因（列表在书库管理页）
    if (!res.failed) open.value = false
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '迁移失败')
  } finally {
    busy.value = ''
  }
}

async function dismiss(): Promise<void> {
  busy.value = 'dismiss'
  try {
    await api.migrationDismiss('启动确认时选择暂不迁移')
    open.value = false
    ui.toast('已记下「暂不迁移」；随时可在「工具 → 书库管理」里再来一次')
  } finally {
    busy.value = ''
  }
}

async function enableAuto(): Promise<void> {
  setVal('libraries.auto_migrate', true)
  await saveSection('libraries')
  await runMigration()
}

function goManage(): void {
  open.value = false
  router.push({ name: 'tools-libraries' })
}
</script>

<template>
  <!-- 阻塞式：没有点遮罩关闭、没有右上角叉（这是要一个明确答复，不是通知） -->
  <div v-if="open && preview" class="fixed inset-0 z-[70] grid place-items-center bg-black/45 p-4">
    <div class="w-[min(40rem,94vw)] max-h-[88vh] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl">
      <h3 class="font-serif text-[17px] font-semibold text-foreground">按格式归库</h3>
      <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
        现有书还没分进各自的库。迁移只**挪库、不改名**，因此书名、阅读进度、批注与评分都不会变；
        目标库已有同名文件时一律拒绝覆盖（只给建议名，不自动改名）。
      </p>

      <div class="mt-3 flex flex-wrap items-center gap-2">
        <Badge tone="accent">待迁移 {{ preview.movable }} 本</Badge>
        <Badge v-for="(n, label) in byType" :key="label">{{ label }} {{ n }}</Badge>
        <Badge v-if="preview.conflict">同名冲突 {{ preview.conflict }}</Badge>
        <Badge v-if="preview.ambiguous">需指定目标 {{ preview.ambiguous }}</Badge>
      </div>

      <!-- 缺目标库：逐库选位置（就地引用 / 独立存储） -->
      <div v-if="preview.suggest_specs.length" class="mt-3 rounded-md border border-border p-3">
        <div class="text-[12.5px] text-foreground">
          需要先建 {{ preview.suggest_specs.length }} 个类型库 —— 逐个选存放方式
        </div>
        <div
          v-for="s in preview.suggest_specs"
          :key="s.id"
          class="mt-2 flex flex-wrap items-center gap-2"
        >
          <span class="text-[12px] font-medium text-foreground">{{ s.name }}</span>
          <code class="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
            {{ s[(specMode[s.id] ?? 'inplace') as 'inplace' | 'import'].root_path }}
          </code>
          <Button
            size="sm"
            :variant="(specMode[s.id] ?? 'inplace') === 'inplace' ? 'primary' : 'ghost'"
            @click="specMode[s.id] = 'inplace'"
          >
            就地引用
          </Button>
          <Button
            size="sm"
            :variant="specMode[s.id] === 'import' ? 'primary' : 'ghost'"
            @click="specMode[s.id] = 'import'"
          >
            独立存储
          </Button>
        </div>
        <div class="mt-2">
          <Button size="sm" :disabled="busy === 'create'" @click="createSuggested">
            {{ busy === 'create' ? '创建中…' : '创建这些书库' }}
          </Button>
        </div>
      </div>

      <div v-if="result" class="mt-3 text-[12px] text-muted-foreground">{{ result }}</div>

      <div class="mt-4 flex flex-wrap items-center gap-2">
        <Button size="sm" :disabled="!!busy || preview.movable === 0" @click="runMigration">
          {{ busy === 'migrate' ? '迁移中…' : '执行迁移' }}
        </Button>
        <Button size="sm" variant="ghost" :disabled="!!busy" @click="dismiss">暂不迁移</Button>
        <Button size="sm" variant="ghost" :disabled="!!busy" @click="enableAuto">
          以后自动执行
        </Button>
        <Button size="sm" variant="ghost" class="ml-auto" @click="goManage">前往书库管理</Button>
      </div>

      <label class="mt-3 flex items-center gap-2 text-[11.5px] text-muted-foreground">
        <input type="checkbox" :checked="autoMigrate" disabled />
        当前设置：{{ autoMigrate ? '已开启「以后自动执行」' : '未开启自动执行' }}
      </label>
    </div>
  </div>
</template>
