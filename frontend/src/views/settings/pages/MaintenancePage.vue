<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { UPLOAD_FIELDS } from '@/data/settingsFields'
import { findSettingsPage } from '@/data/settingsNav'
import {
  api,
  type MaintenanceInfo,
  type OrphansInfo,
  type RecycleListPayload,
  type RecycledItem,
  type RecycleOrphan,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * LIBRARY → Maintenance（`/settings/library/maintenance`）
 *
 * 上游分组为 UPLOADS / IMPORT / RECOMMENDATIONS / ACHIEVEMENTS / UPDATES。
 * 本项目真实能落地的：
 *   · UPLOADS      上传大小上限（**此前后端完全没有限制**，本次补上并真正生效）
 *   · UPDATES      版本检查 + 一键更新 + 自动更新（**第 84 期纠正对照**：
 *                  本项目第 78 期就实现了上游那条「Check for updates」，且做得更多；
 *                  此前误记成「未实现」，本项目把开关放在 ext/update 页）
 *   · 目录与占用    输入 / 导出 / 缓存 / 备份 / 回收站
 *   · 维护动作      重建书库索引、清空缓存、清空回收站
 * 其余三项保持明确「未支持」，条目直接取自注册表，避免与侧栏声明走样。
 */
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

const info = ref<MaintenanceInfo | null>(null)
const orphans = ref<OrphansInfo | null>(null)
const busy = ref('')

/** 回收站台账（第 81 期）：还原的入口就在这一块 */
const recycle = ref<RecycleListPayload | null>(null)
/** 列表里最多显示几条（2400 份的库不该把页面撑爆；计数始终是全量） */
const RECYCLE_SHOWN = 12

/** 只列有孤儿记录的表 */
const orphanTables = computed(() =>
  Object.entries(orphans.value?.tables ?? {})
    .filter(([, v]) => v.books > 0)
    .map(([name, v]) => ({ name, books: v.books, sample: v.sample })),
)

const upstream = computed(() => findSettingsPage('library/maintenance')?.upstream)

/**
 * 已实现的条目不再列入「未支持」。
 *
 * ⚠️ 必须与 `settingsNav.ts` 里 `upstream.items` 的**逐字一致**（这里是精确匹配）：
 * UPDATES 那条在上游条目里带中文括注「（查 GitHub 新版本）」，写成裸 `Check for updates`
 * 匹配不上 —— 表现是它仍留在「上游还有、本项目未支持」卡里，与同页那张「已实现 + 跳转」
 * 的说明卡自相矛盾（`MaintenancePage.spec.ts` 钉住这条）。
 */
const IMPLEMENTED = ['Maximum upload file size limit', 'Backfill achievements',
  'Check for updates（查 GitHub 新版本）']
const unsupportedItems = computed(() =>
  (upstream.value?.items ?? []).filter((i) => !IMPLEMENTED.includes(i)),
)
const unsupportedGroups = computed(() =>
  (upstream.value?.groups ?? []).filter(
    (g) => g !== 'UPLOADS' && g !== 'ACHIEVEMENTS' && g !== 'UPDATES',
  ),
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
  try {
    recycle.value = await api.recycleList()
  } catch {
    // 回收站列举失败同理：不阻塞整页（下面那块会显示「加载中…」）
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

/** 全部按原路径还原（第 81 期）：后台任务，受理即返回；幂等可续跑（成功即删台账行） */
function restoreRecycle(): Promise<void> {
  const n = recycle.value?.total ?? 0
  if (!n) return Promise.resolve()
  const ok = window.confirm(
    `把回收站里的 ${n} 份全部按原路径搬回去？\n\n` +
      '· 目标已存在时会退让改名（绝不覆盖你已有的文件）；\n' +
      '· 后台执行，受理后到「任务中心」看进度；\n' +
      '· 幂等可续跑：还原成功后台账行即删除，再点一次只会跳过。',
  )
  if (!ok) return Promise.resolve()
  return run('restore', '还原回收站', async () => {
    const r = await api.recycleRestore({ all: true })
    return r.task_id
      ? `已受理还原 ${r.total} 份（到任务中心看进度）`
      : (r.errors[0]?.error ?? '没有可还原的条目')
  })
}

function restoreOne(it: RecycledItem): Promise<void> {
  return run(`restore:${it.id}`, '还原', async () => {
    const r = await api.recycleRestore({ ids: [it.id] })
    return r.task_id
      ? `已受理还原：${it.orig_path || it.name}`
      : (r.errors[0]?.error ?? '没有可还原的条目')
  })
}

/**
 * 无台账孤儿还原：无从知道原路径 ⇒ 让用户指定一个目标目录，
 * 文件名会剥掉 `YYYYMMDD-HHMMSS_[n_]` 前缀。
 */
function restoreOrphan(o: RecycleOrphan): Promise<void> {
  const dir = window.prompt(
    `把「${o.stripped}」还原到哪个目录？（绝对路径）\n\n` +
      '这条没有台账（第 81 期之前的回收，或手工放进回收目录的），所以需要你指定目标目录。',
    '',
  )
  if (!dir) return Promise.resolve()
  return run(`restore:${o.name}`, '还原', async () => {
    const r = await api.recycleRestore({ names: [o.name], target_dir: dir })
    if (!r.task_id) return r.errors[0]?.error ?? '没有可还原的条目'
    return `已受理还原「${o.stripped}」→ ${dir}`
  })
}

function clearRecycle(): Promise<void> {
  // 回收站是「重复清理 / 缺失清理」承诺的兜底，清空即不可恢复 —— 必须显式确认
  if (!window.confirm('清空回收站？此为真删，清空后无法恢复（还原台账也一起清掉）。'))
    return Promise.resolve()
  return run('recycle', '清空回收站', async () => {
    const r = await api.clearRecycle()
    return `已清空回收站：删除 ${r.removed} 个文件，释放 ${fmtBytes(r.freed)}（台账 ${r.ledger_cleared} 条）`
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

    <!-- UPDATES（第 84 期）：上游那条「Check for updates」本项目第 78 期就实现了，
         且做得更多（检查间隔 / 拉取镜像 / 一键更新 / 自动更新）。此处只做**跳转**，
         不放重复开关 —— 同一配置键挂两处必然出现「改了一处另一处没跟上」的假开关。 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">版本检查与更新</h3>
        <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          对应上游 UPDATES 分组的 <span class="font-mono">Check for updates</span>
          （启动时查 GitHub 新版本，有更新时侧栏显示指示器）。本项目第 78 期即已实现，
          并在此基础上多做了：可配置的检查间隔、镜像拉取、一键更新、发现新版自动更新
          （自动更新前会自动备份数据，失败按 1 小时 → 6 小时 → 24 小时退避重试）。
          开关与状态都集中在
          <RouterLink to="/settings/ext/update" class="underline">扩展 → 更新</RouterLink> 页。
        </p>
      </div>
      <div class="flex items-center gap-3 px-4 py-3">
        <div class="min-w-0 flex-1 text-[11.5px] text-muted-foreground">
          一键更新与自动更新要求容器挂了
          <code class="font-mono">/var/run/docker.sock</code>（默认不挂载，见部署文件注释）。
        </div>
        <RouterLink to="/settings/ext/update">
          <Button size="sm" variant="primary">前往 Updates 页</Button>
        </RouterLink>
      </div>
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

    <!-- 回收站还原（第 81 期）：只把文件搬进回收站是不够的 —— 关键是把误搬的东西搬回去。
         「移除书库 / 删书 / 清理重复」每次移入都会记一条台账（原路径 + 原因）。 -->
    <Card padding="none" class="mb-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">回收站还原</h3>
        <Badge v-if="recycle" tone="accent">{{ recycle.total }} 条台账</Badge>
        <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">
          {{ recycle ? `无台账 ${recycle.orphan_total} 条` : '—' }}
        </span>
        <Button
          size="sm"
          variant="primary"
          :disabled="!!busy || !recycle?.total"
          @click="restoreRecycle"
        >
          {{ busy === 'restore' ? '处理中…' : '全部按原路径还原' }}
        </Button>
      </div>

      <div class="px-4 py-3">
        <p class="text-[11.5px] leading-relaxed text-muted-foreground">
          「移除书库 / 删书 / 清理重复」把文件移进回收目录时都会记一条台账（原路径 + 原因）。
          还原就是按<strong>原路径</strong>搬回去；目标已存在时<strong>退让改名</strong>，绝不覆盖。
          还原是幂等可续跑的：成功后台账行即删除，再点一次只会跳过。
        </p>

        <div v-if="recycle?.items.length" class="mt-2.5 flex flex-col gap-1.5">
          <div
            v-for="it in recycle.items.slice(0, RECYCLE_SHOWN)"
            :key="it.id"
            class="flex flex-wrap items-center gap-2 rounded-md bg-muted/60 px-2.5 py-1.5"
          >
            <Icon
              :name="it.kind === 'dir' ? 'folder' : 'file'"
              class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span
              class="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground"
              :title="it.orig_path || it.name"
            >
              {{ it.orig_path || it.name }}
            </span>
            <span v-if="it.why" class="shrink-0 text-[10.5px] text-muted-foreground">{{ it.why }}</span>
            <span class="shrink-0 text-[10.5px] text-muted-foreground tabular-nums">
              {{ fmtBytes(it.size) }}
            </span>
            <Button size="sm" variant="ghost" :disabled="!!busy" @click="restoreOne(it)">还原</Button>
          </div>
          <p v-if="recycle.total > RECYCLE_SHOWN" class="text-[11px] text-muted-foreground">
            只列最近 {{ RECYCLE_SHOWN }} 条（共 {{ recycle.total }} 条）——
            用上面的「全部按原路径还原」一次搬回。
          </p>
        </div>
        <p v-else-if="recycle" class="mt-2 text-[11.5px] text-success">没有可还原的台账条目</p>
        <p v-else class="mt-2 text-[11.5px] text-muted-foreground">加载中…</p>
      </div>

      <!-- 无台账孤儿：第 81 期之前的历史回收，或用户手工丢进回收目录的东西 -->
      <div v-if="recycle?.orphans.length" class="border-t border-border px-4 py-3">
        <div class="text-[12px] font-medium text-foreground">
          无台账条目（{{ recycle.orphan_total }}）
        </div>
        <p class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
          这些是第 81 期之前回收的、或手工放进回收目录的：无从知道原路径，还原时由你指定目标目录
          （文件名会剥掉时间戳前缀）。
        </p>
        <div class="mt-2 flex flex-col gap-1.5">
          <div
            v-for="o in recycle.orphans.slice(0, RECYCLE_SHOWN)"
            :key="o.name"
            class="flex flex-wrap items-center gap-2 rounded-md bg-muted/60 px-2.5 py-1.5"
          >
            <Icon
              :name="o.kind === 'dir' ? 'folder' : 'file'"
              class="h-3.5 w-3.5 shrink-0 text-muted-foreground"
            />
            <span class="min-w-0 flex-1 truncate font-mono text-[11px] text-foreground" :title="o.name">
              {{ o.stripped }}
            </span>
            <span class="shrink-0 text-[10.5px] text-muted-foreground tabular-nums">
              {{ fmtBytes(o.size) }}
            </span>
            <Button size="sm" variant="ghost" :disabled="!!busy" @click="restoreOrphan(o)">
              指定目录还原
            </Button>
          </div>
        </div>
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
            重复书籍 / 缺失资源 / 移除书库时移入的文件，连同<strong>还原台账</strong>一起清掉；
            清空后<strong>无法找回</strong>（要还原请先用上面的「回收站还原」）
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
