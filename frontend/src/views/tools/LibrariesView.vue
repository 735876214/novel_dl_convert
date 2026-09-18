<script setup lang="ts">
/**
 * 书库管理（工具页 → 书库管理，第 10 期 D8）。
 *
 * 三块的顺序按**用户遇到的问题**排，而不是按数据结构排：
 *   1. 迁移确认 —— 老部署升级上来第一件要回答的事「我这堆书要不要按格式分家」；
 *   2. 书库列表 —— 建/改/扫/移除；
 *   3. 当前库能力 —— 解释「为什么某些菜单不见了」（否则用户会以为功能丢了）。
 */
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import LibraryConflictPanel from '@/components/tools/LibraryConflictPanel.vue'
import LibrarySettingsPanel from '@/components/tools/LibrarySettingsPanel.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import {
  api,
  type LibraryEntity,
  type LibraryMode,
  type LibraryType,
  type MigrationPreview,
  type MigrationRow,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const library = useLibraryStore()
const { cfg, setVal, saveSection, saving, loadConfig } = useSettingsConfig()

const libs = ref<LibraryEntity[]>([])
const types = ref<{ value: LibraryType; label: string }[]>([])
const modes = ref<{ value: LibraryMode; label: string }[]>([])
const sourceDir = ref('')
const preview = ref<MigrationPreview | null>(null)
const batches = ref<{ batch_id: string; at: number; done: number; pending: number; failed: number }[]>([])
const loading = ref(false)
const busy = ref('')
const detailBatch = ref<MigrationRow[]>([])
const detailOpen = ref(false)
/** 正在展开「每库设置」的书库 id（空 = 收起）：同时只开一个，免得一屏堆满控件 */
const settingsFor = ref('')
/** 同名冲突面板：迁移 / 改名之后要让它重新拉清单 */
const conflicts = ref<InstanceType<typeof LibraryConflictPanel> | null>(null)

function toggleSettings(id: string): void {
  settingsFor.value = settingsFor.value === id ? '' : id
}

/** 向导里为「缺失的类型库」逐库选择的位置方案：`{ 类型: 'inplace' | 'import' }` */
const specMode = ref<Record<string, LibraryMode>>({})

const autoMigrate = computed(() => cfg.value?.libraries?.auto_migrate === true)

async function reload(force = false): Promise<void> {
  loading.value = true
  try {
    const res = await api.libraries()
    libs.value = res.items
    types.value = res.types
    modes.value = res.modes
    sourceDir.value = res.source_dir
    await library.loadLibraries(true)
    preview.value = await api.migrationPreview()
    for (const s of preview.value.suggest_specs) specMode.value[s.id] ??= 'inplace'
    const b = await api.migrationBatches()
    batches.value = b.items
    if (force) await library.loadBooks(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '加载书库信息失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void reload()
  void loadConfig(false, true)
})

// ---------------- 迁移 ----------------

/** 逐库创建缺失的类型库（**只登记，不搬文件**）。 */
async function createSuggested(): Promise<void> {
  const specs = preview.value?.suggest_specs ?? []
  if (!specs.length) return
  busy.value = 'create'
  try {
    for (const s of specs) {
      const mode = specMode.value[s.id] ?? 'inplace'
      const loc = s[mode]
      await api.createLibrary({
        name: s.name,
        type: s.type,
        mode,
        root_path: loc.root_path,
        source_subdir: s.source_subdir,
      })
    }
    ui.toast(`已创建 ${specs.length} 个书库`)
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '创建失败')
  } finally {
    busy.value = ''
  }
}

async function runMigration(): Promise<void> {
  busy.value = 'migrate'
  try {
    const planned = await api.migrationPlan()
    if (!planned.batch_id) {
      ui.toast(planned.message || '没有可迁移的书')
      await reload()
      return
    }
    const res = await api.migrationApply(planned.batch_id)
    ui.toast(`已迁移 ${res.moved ?? 0} 本${res.failed ? `，失败 ${res.failed} 本` : ''}`)
    detailBatch.value = res.items
    detailOpen.value = res.failed > 0
    await reload(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '迁移失败')
  } finally {
    busy.value = ''
  }
}

async function rollbackLast(): Promise<void> {
  busy.value = 'rollback'
  try {
    const res = await api.migrationRollback()
    ui.toast(`已回滚 ${res.restored ?? 0} 本`)
    await reload(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '回滚失败')
  } finally {
    busy.value = ''
  }
}

async function dismissGate(): Promise<void> {
  busy.value = 'dismiss'
  try {
    await api.migrationDismiss('在书库管理页选择暂不迁移')
    ui.toast('已记下「暂不迁移」，之后不再每次启动提示')
    await reload()
  } finally {
    busy.value = ''
  }
}

async function resetGate(): Promise<void> {
  await api.migrationResetGate()
  ui.toast('已恢复启动提示')
  await reload()
}

async function toggleAutoMigrate(): Promise<void> {
  setVal('libraries.auto_migrate', !autoMigrate.value)
  const ok = await saveSection('libraries')
  if (ok) await reload()
}

// ---------------- 新建 / 编辑 ----------------

const dialogOpen = ref(false)
const editingId = ref('')
const form = ref({
  name: '',
  type: 'ebook' as LibraryType,
  mode: 'inplace' as LibraryMode,
  root_path: '',
  source_subdir: '',
  rules: '',
})

function defaultRoot(mode: LibraryMode, type: LibraryType): string {
  return mode === 'inplace' ? `${sourceDir.value}/${type}s` : `${sourceDir.value}/../data/libraries/${type}`
}

function openCreate(): void {
  editingId.value = ''
  form.value = {
    name: '',
    type: 'ebook',
    mode: 'inplace',
    root_path: '',
    source_subdir: '',
    rules: '',
  }
  dialogOpen.value = true
}

function openEdit(l: LibraryEntity): void {
  editingId.value = l.id
  form.value = {
    name: l.name,
    type: l.type,
    mode: l.mode,
    root_path: l.root_path,
    source_subdir: l.source_subdir,
    rules: l.rules,
  }
  dialogOpen.value = true
}

async function submitDialog(): Promise<void> {
  busy.value = 'save'
  try {
    const payload = {
      name: form.value.name.trim(),
      type: form.value.type,
      mode: form.value.mode,
      root_path: form.value.root_path.trim() || defaultRoot(form.value.mode, form.value.type),
      source_subdir: form.value.source_subdir.trim(),
      rules: form.value.rules,
    }
    if (editingId.value) {
      await api.updateLibrary(editingId.value, payload)
      ui.toast('书库已更新')
    } else {
      await api.createLibrary(payload)
      ui.toast('书库已创建')
    }
    dialogOpen.value = false
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = ''
  }
}

async function scan(l: LibraryEntity): Promise<void> {
  busy.value = `scan:${l.id}`
  try {
    const res = await api.scanLibrary(l.id)
    ui.toast(`「${l.name}」扫描完成：${res.count} 本`)
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  } finally {
    busy.value = ''
  }
}

async function remove(l: LibraryEntity): Promise<void> {
  if (l.book_count > 0) {
    ui.toast(`「${l.name}」还有 ${l.book_count} 本书：请先迁移走（移除登记不会动文件）`)
    return
  }
  if (!window.confirm(`移除书库「${l.name}」的登记？（**不会删除任何文件**）`)) return
  busy.value = `del:${l.id}`
  try {
    await api.deleteLibrary(l.id)
    ui.toast('已移除登记')
    await reload()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '移除失败')
  } finally {
    busy.value = ''
  }
}

</script>

<template>
  <div class="space-y-4">
    <!-- 1) 迁移确认 -->
    <Card v-if="preview && preview.total > 0" padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">按格式归库</span>
          <Badge tone="accent">待迁移 {{ preview.total }}</Badge>
          <Badge v-if="preview.conflict">同名冲突 {{ preview.conflict }}</Badge>
          <Badge v-if="preview.no_library">缺目标库 {{ preview.no_library }}</Badge>
          <span class="ml-auto text-[11.5px] text-muted-foreground">
            迁移只<strong>挪库不改名</strong>，进度与批注不会断链
          </span>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          电子书 / 漫画 / 有声书按<strong>格式</strong>分到各自的库；同名文件一律拒绝覆盖并给出建议名
          （改名会换 book_id，所以只建议、不自动改）。
        </div>
      </div>

      <!-- 缺失的类型库：逐库选位置 -->
      <div v-if="preview.suggest_specs.length" class="border-b border-border px-4 py-3">
        <div class="text-[12.5px] text-foreground">
          还缺 {{ preview.suggest_specs.length }} 个类型库（{{ preview.missing_labels.join('、') }}）——
          逐个选存放方式，再一并创建
        </div>
        <div
          v-for="s in preview.suggest_specs"
          :key="s.id"
          class="mt-2 flex flex-wrap items-center gap-2 rounded-md border border-border px-3 py-2"
        >
          <Badge>{{ s.name }}</Badge>
          <span class="text-[11.5px] text-muted-foreground">
            {{ specMode[s.id] === 'import' ? '独立存储' : '就地引用' }}:
            {{ s[specMode[s.id] ?? 'inplace'].root_path }}
          </span>
          <div class="ml-auto flex gap-1">
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
        </div>
        <div class="mt-2">
          <Button size="sm" :disabled="busy === 'create'" @click="createSuggested">
            {{ busy === 'create' ? '创建中…' : `创建这 ${preview.suggest_specs.length} 个书库` }}
          </Button>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 px-4 py-3">
        <Button
          size="sm"
          :disabled="!!busy || preview.movable === 0"
          @click="runMigration"
        >
          {{ busy === 'migrate' ? '迁移中…' : `执行迁移（${preview.movable} 本）` }}
        </Button>
        <Button size="sm" variant="ghost" :disabled="!!busy" @click="rollbackLast">
          回滚上次迁移
        </Button>
        <Button v-if="!preview.gate.dismissed" size="sm" variant="ghost" :disabled="!!busy" @click="dismissGate">
          暂不迁移
        </Button>
        <Button v-else size="sm" variant="ghost" @click="resetGate">恢复启动提示</Button>
        <label class="ml-auto flex items-center gap-2 text-[11.5px] text-muted-foreground">
          <input type="checkbox" :checked="autoMigrate" :disabled="saving" @change="toggleAutoMigrate" />
          以后自动执行（不再确认）
        </label>
      </div>

      <div v-if="preview.blocked" class="border-t border-border px-4 py-2 text-[11.5px] text-muted-foreground">
        有 {{ preview.blocked }} 条被拦下（同名冲突 / 需指定目标库），它们不会被迁移 ——
        处理后可再次点「执行迁移」。
      </div>
    </Card>

    <!-- 2) 书库列表 -->
    <Card padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">书库</span>
          <Badge>{{ libs.length }}</Badge>
          <Button size="sm" class="ml-auto" @click="openCreate">新建书库</Button>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          来源父目录：<code>{{ sourceDir || '—' }}</code>（「就地引用」直接引用它下面的子目录，不搬文件）
        </div>
      </div>

      <div v-if="loading && !libs.length" class="px-4 py-6 text-[12.5px] text-muted-foreground">加载中…</div>
      <div v-else-if="!libs.length" class="px-4 py-6 text-[12.5px] text-muted-foreground">还没有书库</div>

      <div
        v-for="l in libs"
        :key="l.id"
        class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3 last:border-b-0"
      >
        <div class="min-w-0 flex-1">
          <div class="flex flex-wrap items-center gap-2">
            <span class="text-[12.5px] font-medium text-foreground">{{ l.name }}</span>
            <Badge tone="accent">{{ l.type_label }}</Badge>
            <Badge>{{ l.mode_label }}</Badge>
            <Badge v-if="l.is_default">默认</Badge>
            <Badge v-if="!l.exists">根目录不存在</Badge>
            <Badge v-else-if="!l.writable">只读</Badge>
            <span class="text-[11.5px] text-muted-foreground">{{ l.book_count }} 本</span>
          </div>
          <div class="mt-0.5 truncate text-[11.5px] text-muted-foreground" :title="l.root_path">
            {{ l.root_path }}
            <span v-if="l.source_subdir"> · 来源子目录 {{ l.source_subdir }}</span>
            <span v-if="l.last_scan_note"> · {{ l.last_scan_note }}</span>
          </div>
        </div>
        <div class="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" @click="toggleSettings(l.id)">
            {{ settingsFor === l.id ? '收起设置' : '设置' }}
          </Button>
          <Button size="sm" variant="ghost" :disabled="!!busy" @click="scan(l)">
            {{ busy === `scan:${l.id}` ? '扫描中…' : '扫描' }}
          </Button>
          <Button size="sm" variant="ghost" @click="openEdit(l)">编辑</Button>
          <Button
            v-if="!l.is_default"
            size="sm"
            variant="ghost"
            :disabled="!!busy"
            @click="remove(l)"
          >
            移除
          </Button>
        </div>
      </div>
    </Card>

    <!-- 2.5) 逐库设置：把投递 / 元数据 / 命名按库分开（未设的项继承全局） -->
    <Card v-if="settingsFor" padding="none">
      <LibrarySettingsPanel :library-id="settingsFor" @changed="reload(true)" />
    </Card>

    <!-- 3) 当前库能力（解释「为什么某些菜单不见了」） -->
    <Card padding="none">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[13px] font-medium text-foreground">当前库：{{ library.currentLibraryName }}</span>
          <Badge v-if="!library.currentLibraryId" tone="accent">不裁剪</Badge>
        </div>
        <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          侧栏导航 / 工具标签 / 设置项 / 仪表盘部件按<strong>当前库的能力</strong>裁剪；
          选「全部书库」时不做任何裁剪。
        </div>
      </div>
      <div class="flex flex-wrap gap-1.5 px-4 py-3">
        <Badge v-for="f in library.features" :key="f" tone="accent">
          {{ library.featureLabels[f] || f }}
        </Badge>
        <span v-if="!library.features.length" class="text-[11.5px] text-muted-foreground">
          （全部书库：不裁剪）
        </span>
      </div>
    </Card>

    <!-- 3.5) 同名冲突：book_id 由文件名派生，跨库同名会撞同一个 id -->
    <Card padding="none">
      <LibraryConflictPanel ref="conflicts" @changed="reload(true)" />
    </Card>

    <!-- 迁移台账 -->
    <Card v-if="batches.length" padding="none">
      <div class="border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">迁移台账</span>
        <span class="ml-2 text-[11.5px] text-muted-foreground">最近 {{ batches.length }} 个批次</span>
      </div>
      <div
        v-for="b in batches"
        :key="b.batch_id"
        class="flex items-center gap-3 border-b border-border px-4 py-2 text-[11.5px] last:border-b-0"
      >
        <code class="text-foreground">{{ b.batch_id }}</code>
        <span class="text-muted-foreground">成功 {{ b.done }}</span>
        <span v-if="b.pending" class="text-muted-foreground">待处理 {{ b.pending }}</span>
        <span v-if="b.failed" class="text-destructive">失败 {{ b.failed }}</span>
      </div>
    </Card>

    <!-- 明细（迁移后失败项） -->
    <Card v-if="detailOpen && detailBatch.length" padding="none">
      <div class="border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">本次明细</span>
        <Button size="sm" variant="ghost" class="ml-2" @click="detailOpen = false">收起</Button>
      </div>
      <div
        v-for="r in detailBatch"
        :key="r.id"
        class="flex items-center gap-3 border-b border-border px-4 py-2 text-[11.5px] last:border-b-0"
      >
        <Badge :tone="r.status === 'done' ? 'accent' : undefined">{{ r.status }}</Badge>
        <span class="min-w-0 flex-1 truncate" :title="r.src">{{ r.src }}</span>
        <span v-if="r.error" class="text-destructive">{{ r.error }}</span>
      </div>
    </Card>

    <!-- 新建 / 编辑弹窗 -->
    <div
      v-if="dialogOpen"
      class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
      @click.self="dialogOpen = false"
    >
      <div class="w-[min(34rem,94vw)] rounded-lg border border-border bg-card p-5 shadow-2xl">
        <h3 class="mb-3 font-serif text-[16px] font-semibold text-foreground">
          {{ editingId ? '编辑书库' : '新建书库' }}
        </h3>

        <div class="space-y-3">
          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">名称</div>
            <input
              v-model="form.name"
              class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              placeholder="如：漫画库"
            />
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">类型（决定功能显隐）</div>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="t in types"
                :key="t.value"
                size="sm"
                :variant="form.type === t.value ? 'primary' : 'ghost'"
                @click="form.type = t.value"
              >
                {{ t.label }}
              </Button>
            </div>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">存放方式</div>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="m in modes"
                :key="m.value"
                size="sm"
                :variant="form.mode === m.value ? 'primary' : 'ghost'"
                @click="form.mode = m.value; form.root_path = defaultRoot(m.value, form.type)"
              >
                {{ m.label }}
              </Button>
            </div>
            <div class="mt-1 text-[11px] text-muted-foreground">
              就地引用 = 直接引用来源子目录（不搬文件）；独立存储 = 库有自己的存储目录，「来源目录」的文件会导入进来。
            </div>
          </div>

          <div>
            <div class="mb-1 text-[11.5px] text-muted-foreground">库根目录（留空用默认）</div>
            <input
              v-model="form.root_path"
              :placeholder="defaultRoot(form.mode, form.type)"
              class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            />
            <div class="mt-1 text-[11px] text-muted-foreground">
              必须在「书库来源目录 / 导出目录 / 数据目录」之内 —— 否则可能误扫、甚至误移系统文件。
            </div>
          </div>

          <div class="flex flex-wrap gap-3">
            <div class="min-w-[10rem] flex-1">
              <div class="mb-1 text-[11.5px] text-muted-foreground">来源子目录名</div>
              <input
                v-model="form.source_subdir"
                placeholder="如：comics"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>
            <div class="min-w-[10rem] flex-[2]">
              <div class="mb-1 text-[11.5px] text-muted-foreground">归类关键词（逗号分隔）</div>
              <input
                v-model="form.rules"
                placeholder="如：科幻, 太空"
                class="w-full rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
              />
            </div>
          </div>
        </div>

        <div class="mt-4 flex justify-end gap-2">
          <Button size="sm" variant="ghost" @click="dialogOpen = false">取消</Button>
          <Button size="sm" :disabled="busy === 'save' || !form.name.trim()" @click="submitDialog">
            {{ busy === 'save' ? '保存中…' : '保存' }}
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
