<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { UPLOAD_FIELDS } from '@/data/settingsFields'
import { findSettingsPage } from '@/data/settingsNav'
import {
  api,
  type MaintenanceInfo,
  type OrphansInfo,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * LIBRARY → Maintenance（`/settings/library/maintenance`）
 *
 * 上游分组为 UPLOADS / IMPORT / RECOMMENDATIONS / ACHIEVEMENTS / UPDATES。
 * 本项目真实能落地的：
 *   · UPLOADS      上传大小上限（**此前后端完全没有限制**，本次补上并真正生效）
 *   · 目录与占用    输入 / 导出 / 缓存 / 备份 / 回收站
 *   · 维护动作      重建书库索引、清空缓存、清空回收站
 * 其余四项保持明确「未支持」，条目直接取自注册表，避免与侧栏声明走样。
 */
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

const info = ref<MaintenanceInfo | null>(null)
const orphans = ref<OrphansInfo | null>(null)
const busy = ref('')

/** 只列有孤儿记录的表 */
const orphanTables = computed(() =>
  Object.entries(orphans.value?.tables ?? {})
    .filter(([, v]) => v.books > 0)
    .map(([name, v]) => ({ name, books: v.books, sample: v.sample })),
)

const upstream = computed(() => findSettingsPage('library/maintenance')?.upstream)

/** 已实现的条目不再列入「未支持」 */
const IMPLEMENTED = ['Maximum upload file size limit', 'Backfill achievements']
const unsupportedItems = computed(() =>
  (upstream.value?.items ?? []).filter((i) => !IMPLEMENTED.includes(i)),
)
const unsupportedGroups = computed(() =>
  (upstream.value?.groups ?? []).filter((g) => g !== 'UPLOADS' && g !== 'ACHIEVEMENTS'),
)

const DIR_LABELS: Record<string, string> = {
  input: '输入目录',
  output: '导出目录',
  cache: '缓存目录',
  backups: '配置备份',
  recycle: '回收站',
}

const dirs = computed(() => {
  const d = info.value?.dirs
  if (!d) return []
  return (['input', 'output', 'cache', 'backups', 'recycle'] as const).map((k) => ({
    key: k,
    label: DIR_LABELS[k],
    ...d[k],
  }))
})

function fmtBytes(n: number | undefined | null): string {
  if (n === undefined || n === null) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return i === 0 ? `${v} B` : `${v.toFixed(1)} ${units[i]}`
}

function mbOf(bytes: number | undefined): string {
  if (!bytes) return '—'
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function refresh(): Promise<void> {
  try {
    info.value = await api.maintenance()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '维护信息加载失败')
  }
  try {
    orphans.value = await api.orphans()
  } catch {
    // 孤儿扫描失败不阻塞整页：它只是维护页里的其中一块
  }
}

async function run(key: string, label: string, fn: () => Promise<string>): Promise<void> {
  busy.value = key
  try {
    ui.toast(await fn())
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : `${label}失败`)
  } finally {
    busy.value = ''
    await refresh()
  }
}

function rebuild(): Promise<void> {
  return run('rebuild', '重建索引', async () => {
    const r = await api.rebuildLibrary()
    return `书库索引已重建：${r.books} 本`
  })
}

function clearCache(): Promise<void> {
  return run('cache', '清空缓存', async () => {
    const r = await api.clearCache()
    return `已清理缓存 ${r.removed} 项（回收站已保留）`
  })
}

function clearRecycle(): Promise<void> {
  // 回收站是「重复清理 / 缺失清理」承诺的兜底，清空即不可恢复 —— 必须显式确认
  if (!window.confirm('清空回收站？此为真删，清空后无法恢复。')) return Promise.resolve()
  return run('recycle', '清空回收站', async () => {
    const r = await api.clearRecycle()
    return `已清空回收站：删除 ${r.removed} 个文件，释放 ${fmtBytes(r.freed)}`
  })
}

function backfillAchievements(): Promise<void> {
  // 对应上游 Maintenance 的 Backfill achievements：清空解锁记录后按当前数据重判，
  // 解锁时间会被重置为此刻。是可逆的（重判后会重新解锁），但不保留原解锁时间，故加说明。
  return run('achievements', '重算成就', async () => {
    const r = await api.backfillAchievements()
    return r.backfilled
      ? `已重算成就：${r.unlocked}/${r.total} 项解锁（解锁时间已重置为现在）`
      : '成就未启用，无需重算'
  })
}

/** 孤儿记录：清掉的可能是「文件放回后还能关联上」的数据，所以必须显式确认并说明后果 */
function clearOrphans(): Promise<void> {
  const ok = window.confirm(
    '清理孤儿记录？\n\n' +
      '这些行指向已不存在的书，界面上已无法访问。清理后不可恢复；\n' +
      '但若把同一个文件放回导出目录，进度与批注会重新关联 —— 也就是清掉的是「可能还有用」的数据。',
  )
  if (!ok) return Promise.resolve()
  return run('orphans', '清理孤儿记录', async () => {
    const r = await api.clearOrphans()
    return r.total ? `已清理 ${r.total} 行孤儿记录` : '没有需要清理的孤儿记录'
  })
}

async function save(): Promise<void> {
  const ok = await saveSection('upload')
  if (ok) await refresh()
}

onMounted(async () => {
  await loadConfig()
  await refresh()
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">维护</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Maintenance</span>
      <Badge tone="accent">部分实现</Badge>
      <span class="text-[11.5px] text-muted-foreground">上传限制、目录占用与清理动作</span>
      <Button size="sm" variant="primary" class="ml-auto" :disabled="saving" @click="save">保存</Button>
    </div>
    <p v-if="upstream?.desc" class="mb-3 font-mono text-[11px] text-muted-foreground">
      {{ upstream.desc }}
    </p>

    <!-- UPLOADS：上传大小上限 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">上传大小上限</h3>
        <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          对应上游 UPLOADS 分组的 <span class="font-mono">Maximum upload file size limit</span>。
          此前两个上传接口都直接读取整个请求体且<strong>没有任何上限</strong>，超大文件可打满容器内存；
          现在按上限分块读取，超限返回 413 且不落盘。
        </p>
      </div>

      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in UPLOAD_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />
        <div class="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-3 text-[11.5px] text-muted-foreground">
          <span>
            当前生效：单本书
            <span class="font-mono text-foreground">{{ fmtBytes(info?.upload.max_bytes) }}</span>
            （{{ mbOf(info?.upload.max_bytes) }}）
          </span>
          <span>
            书源文件
            <span class="font-mono text-foreground">{{ fmtBytes(info?.upload.max_source_rules_bytes) }}</span>
          </span>
          <span v-if="info?.overridden.includes('upload.max_bytes')" class="text-warning">
            已被 settings.json 覆盖
          </span>
        </div>
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <!-- 目录与占用 -->
    <Card padding="none" class="mb-4">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">目录与占用</h3>
        <span class="ml-auto text-[11.5px] text-muted-foreground">
          书库共 {{ info?.library.books ?? '—' }} 本
        </span>
        <Button size="sm" :disabled="!!busy" @click="refresh">刷新</Button>
      </div>

      <div
        v-for="d in dirs"
        :key="d.key"
        class="flex flex-wrap items-center gap-x-3 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <span class="w-20 shrink-0 text-[12.5px] text-foreground">{{ d.label }}</span>
        <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground">
          {{ d.path }}
        </span>
        <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ d.files }} 个文件</span>
        <span class="w-20 shrink-0 text-right text-[11.5px] font-semibold text-foreground tabular-nums">
          {{ fmtBytes(d.bytes) }}
        </span>
      </div>
    </Card>

    <!-- 孤儿记录：上游 Maintenance 的 orphans。本项目没有独立封面目录（封面在 EPUB 内部），
         对应物是数据库里指向已消失书籍的行。 -->
    <Card padding="none" class="mb-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">孤儿记录</h3>
        <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">
          {{ orphans ? `${orphans.total} 条` : '—' }}
        </span>
      </div>

      <div class="px-4 py-3">
        <p class="text-[11.5px] leading-relaxed text-muted-foreground">
          指向<strong>已不存在的书</strong>的数据库行（阅读进度 / 批注 / 收藏项 / 阅读会话）。
          书从导出目录移走后，这些行在界面上再也走不到，却一直占着库。
          本项目没有独立的封面目录（封面在 EPUB 内部），所以 orphans 的对应物就是这些数据库行。
        </p>

        <div v-if="orphanTables.length" class="mt-2.5 flex flex-col gap-1.5">
          <div
            v-for="t in orphanTables"
            :key="t.name"
            class="flex flex-wrap items-baseline gap-2 rounded-md bg-muted/60 px-2.5 py-1.5"
          >
            <span class="font-mono text-[11.5px] text-foreground">{{ t.name }}</span>
            <span class="text-[11.5px] text-muted-foreground tabular-nums">{{ t.books }} 本书</span>
            <span class="min-w-0 flex-1 truncate font-mono text-[10.5px] text-muted-foreground">
              {{ t.sample.slice(0, 3).join(' , ') }}
            </span>
          </div>
        </div>
        <p v-else-if="orphans" class="mt-2 text-[11.5px] text-success">没有孤儿记录</p>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
        <div class="min-w-0 flex-1 text-[11.5px] leading-relaxed text-muted-foreground">
          清理<strong>不可恢复</strong>；但把同一个文件放回导出目录，进度与批注会<strong>重新关联</strong> ——
          也就是清掉的是「可能还有用」的数据，所以需要你确认。
        </div>
        <Button
          size="sm"
          variant="danger"
          :disabled="!!busy || !orphans?.total"
          @click="clearOrphans"
        >
          {{ busy === 'orphans' ? '处理中…' : '清理孤儿记录' }}
        </Button>
      </div>
    </Card>

    <!-- 维护动作 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">维护动作</h3>
        <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          清理动作互不混淆：清缓存<strong>保留</strong>回收站；清空回收站是真删，需二次确认。
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-3">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">重算成就</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            对应上游 Backfill achievements：清空解锁记录后按当前数据重判，
            <strong>解锁时间会重置为现在</strong>（可逆，重判后会重新解锁）
          </div>
        </div>
        <Button size="sm" :disabled="!!busy" @click="backfillAchievements">
          {{ busy === 'achievements' ? '处理中…' : '重算' }}
        </Button>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-3">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">重建书库索引</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            清掉扫描缓存并强制重扫导出目录；只读操作，不改动任何文件
          </div>
        </div>
        <Button size="sm" :disabled="!!busy" @click="rebuild">
          {{ busy === 'rebuild' ? '处理中…' : '重建' }}
        </Button>
      </div>

      <div class="flex flex-wrap items-center gap-3 border-b border-border/60 px-4 py-3">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">清空缓存</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            AI 分章缓存与监听状态；不影响成品，也<strong>不会</strong>动回收站
          </div>
        </div>
        <Button size="sm" :disabled="!!busy" @click="clearCache">
          {{ busy === 'cache' ? '处理中…' : '清空' }}
        </Button>
      </div>

      <div class="flex flex-wrap items-center gap-3 px-4 py-3">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">清空回收站</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            重复书籍 / 缺失资源清理时移入的文件；清空后<strong>无法找回</strong>
          </div>
        </div>
        <Button size="sm" variant="danger" :disabled="!!busy" @click="clearRecycle">
          {{ busy === 'recycle' ? '处理中…' : '清空回收站' }}
        </Button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      :label="upstream?.title ?? 'Maintenance'"
      :groups="unsupportedGroups"
      :items="unsupportedItems"
      note="以上条目在上游 Maintenance 页存在，本项目未实现，仅作只读对照。"
    />
  </div>
</template>
