<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type KomgaLayoutItem, type KomgaLayoutPlan } from '@/lib/api'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * DEVICES → Komga（`/settings/komga`）
 *
 * Komga 是漫画/电子书服务器，扫描**库根目录**：``系列名/书文件``（一层目录），
 * 卷号从文件名解析（``系列 #1.cbz``）。本项目的输出默认是**全平铺**的 ——
 * 同一系列的多卷会被 Komga 当成一堆独立「系列」。
 *
 * 这一页做两件事：
 *   1. **输出布局**：以后转换/入库的书直接按 Komga 结构落盘；
 *   2. **整理既有库**：把已经平铺的书收进系列目录（先预览、再应用）。
 *
 * 未支持「从 Komga 拉书 / 进度同步」（接入侧）——那是另一套 REST 客户端，
 * 与本页互不重叠。
 */
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

onMounted(() => loadConfig())

const isKomga = computed(() => String(val('output.layout') || 'flat') === 'komga')

// ---- 兼容服务端（第三方 Komga 客户端直连本应用）----
const komga = computed<Record<string, any>>(() => (cfg.value as any)?.komga ?? {})
/** 客户端里填的「服务器地址」就是本应用的根地址（它会自己拼 /api/v1） */
const serverUrl = computed(() => window.location.origin)
const copiedServer = ref(false)

async function copyServer(): Promise<void> {
  try {
    await navigator.clipboard.writeText(serverUrl.value)
    copiedServer.value = true
    setTimeout(() => (copiedServer.value = false), 1500)
  } catch {
    ui.toast('复制失败，请手动选中地址')
  }
}

async function toggleLayout(): Promise<void> {
  const next = isKomga.value ? 'flat' : 'komga'
  setVal('output.layout', next)
  const ok = await saveSection('komga')
  if (ok) ui.toast(next === 'komga' ? '新书将按 Komga 布局落盘' : '已切回平铺布局')
}

// ---------------- 整理既有库 ----------------
const plan = ref<KomgaLayoutPlan | null>(null)
const picked = ref<Set<string>>(new Set())
const busy = ref(false)
/** 预览失败信息：留在页面内并可重试，而不是只弹一条转瞬即逝的 toast */
const planError = ref('')
/** 展示层筛选 / 排序：只影响展示，不影响提交范围（提交 = 已勾选项） */
const q = ref('')
const onlyConflict = ref(false)
const sortBy = ref<'series' | 'path'>('series')

async function preview(): Promise<void> {
  busy.value = true
  planError.value = ''
  try {
    const p = await api.komgaLayoutPreview()
    plan.value = p
    // 默认勾选全部无冲突条目：整理是个「我全都要」的动作
    picked.value = new Set(p.items.filter((i) => !i.conflict).map((i) => i.old))
  } catch (e) {
    // 预览失败必须留在页面上（可重试），不能只弹一条转瞬即逝的提示
    plan.value = null
    planError.value = e instanceof Error ? e.message : '预览失败'
  } finally {
    busy.value = false
  }
}

function togglePick(old: string): void {
  const s = new Set(picked.value)
  if (s.has(old)) s.delete(old)
  else s.add(old)
  picked.value = s
}

const pickedItems = computed(() =>
  (plan.value?.items ?? []).filter((i) => picked.value.has(i.old) && !i.conflict),
)
const pickedIdChanges = computed(() => pickedItems.value.filter((i) => i.id_changes).length)

// ---- 预览列表的展示层筛选 / 排序（computed 派生，不改 plan.items 原数组） ----
const conflictCount = computed(() => (plan.value?.items ?? []).filter((i) => i.conflict).length)

const visibleItems = computed<KomgaLayoutItem[]>(() => {
  const kw = q.value.trim().toLowerCase()
  const list = (plan.value?.items ?? []).filter((i) => {
    if (onlyConflict.value && !i.conflict) return false
    if (!kw) return true
    return [i.title, i.series, i.old, i.new].some((s) => String(s ?? '').toLowerCase().includes(kw))
  })
  return [...list].sort((a, b) =>
    sortBy.value === 'series'
      ? String(a.series ?? '').localeCompare(String(b.series ?? ''), 'zh') ||
        (Number(a.index) || 0) - (Number(b.index) || 0) ||
        String(a.old).localeCompare(String(b.old), 'zh')
      : String(a.old).localeCompare(String(b.old), 'zh'),
  )
})

/** 可见项里的可勾选项（冲突项后端会拒，勾了也没意义） */
const selectableVisible = computed(() => visibleItems.value.filter((i) => !i.conflict))
const allVisiblePicked = computed(
  () =>
    selectableVisible.value.length > 0 &&
    selectableVisible.value.every((i) => picked.value.has(i.old)),
)

/** 全选/清空只作用于**当前可见**项；筛选隐藏的已勾选项不受影响（提交范围始终 = 已勾选） */
function toggleAllVisible(): void {
  const s = new Set(picked.value)
  if (allVisiblePicked.value) for (const i of selectableVisible.value) s.delete(i.old)
  else for (const i of selectableVisible.value) s.add(i.old)
  picked.value = s
}

async function apply(): Promise<void> {
  if (!pickedItems.value.length) {
    ui.toast('先选要整理的书')
    return
  }
  const n = pickedItems.value.length
  const warn = pickedIdChanges.value
    ? `其中 ${pickedIdChanges.value} 本会改名，阅读进度 / 批注 / 评分 / 收藏会同步迁移。`
    : ''
  if (!window.confirm(`将移动 ${n} 本书到系列目录，确定？${warn}`)) return
  busy.value = true
  try {
    const r = await api.komgaLayoutApply(pickedItems.value.map((i) => ({ old: i.old, new: i.new })))
    const extra = r.remapped ? `，${r.remapped} 本已迁移阅读数据` : ''
    ui.toast(`已整理 ${r.count} 本${extra}` + (r.errors.length ? `，${r.errors.length} 条失败` : ''))
    plan.value = null
    picked.value = new Set()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '整理失败')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">Komga</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Komga</span>
      <span class="text-[11.5px] text-muted-foreground">让本项目的输出符合 Komga 的库结构</span>
      <span
        v-if="isKomga"
        class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
      >
        布局已开启
      </span>
      <span v-else class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">平铺（默认）</span>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">输出布局</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启后，<strong>有系列</strong>的书按 <code class="font-mono">系列名/系列名 #N.ext</code> 落盘；
            无系列的书仍然平铺（Komga 会把它当成一个独立系列，这是合理结果）
          </div>
        </div>
        <Button size="sm" :variant="isKomga ? 'ghost' : 'primary'" :disabled="saving || !cfg" @click="toggleLayout">
          {{ isKomga ? '关闭' : '开启' }}
        </Button>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">整理既有库</div>
        <div class="mb-2.5 text-[11.5px] text-muted-foreground">
          把已经平铺的书收进系列目录。系列来自 EPUB 内的 <code class="font-mono">calibre:series</code>，
          判不出时从<strong>文件名</strong>推断（<code class="font-mono">系列 第01卷</code> /
          <code class="font-mono">系列 #1</code> / <code class="font-mono">系列 (01)</code> 这类）；
          两者都判不出的书原地不动 —— 凭空造一个系列名比平铺更糟。
        </div>
        <Button size="sm" :disabled="busy" @click="preview">
          {{ busy ? '处理中…' : '预览整理方案' }}
        </Button>
      </div>
    </Card>

    <!-- 预览失败：页面内错误态 + 重试（不再只弹 toast） -->
    <Card v-if="planError" class="mt-4" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>整理预览失败：{{ planError }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" :disabled="busy" @click="preview">重试</Button>
      </div>
    </Card>

    <Card v-if="plan" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">整理预览</span>
        <Badge tone="accent">可移动 {{ plan.movable }} 本</Badge>
        <Badge>{{ plan.series_count }} 个系列</Badge>
        <Badge v-if="plan.id_changing">其中 {{ plan.id_changing }} 本会改名（迁移阅读数据）</Badge>
        <Badge>{{ plan.unchanged }} 本无需移动</Badge>
        <div class="ml-auto flex items-center gap-2">
          <span class="text-[12px] text-muted-foreground">已选 {{ pickedItems.length }} 本</span>
          <Button size="sm" variant="primary" :disabled="busy || !pickedItems.length" @click="apply">
            应用
          </Button>
          <Button size="sm" variant="ghost" @click="plan = null">取消</Button>
        </div>
      </div>

      <!-- 展示层筛选 / 排序：只影响展示，提交范围仍是「已勾选」 -->
      <div
        v-if="plan.items.length"
        class="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-4 py-2"
      >
        <input
          v-model="q"
          type="text"
          aria-label="搜索待整理的书"
          placeholder="搜索书名 / 系列 / 路径…"
          class="h-7 min-w-0 flex-1 rounded-md border border-border bg-card px-2.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
        >
        <select
          v-model="sortBy"
          aria-label="排序方式"
          class="h-7 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
        >
          <option value="series">按系列</option>
          <option value="path">按当前路径</option>
        </select>
        <label class="flex cursor-pointer items-center gap-1.5 text-[12px] text-muted-foreground">
          <input v-model="onlyConflict" type="checkbox" class="h-3.5 w-3.5 cursor-pointer accent-primary">
          只看冲突（{{ conflictCount }}）
        </label>
        <button
          type="button"
          class="cursor-pointer rounded-md border border-border px-2.5 py-1 text-[12px] text-foreground transition-colors hover:bg-muted"
          @click="toggleAllVisible"
        >
          {{ allVisiblePicked ? '清空可见项' : '全选可见项' }}
        </button>
        <span class="basis-full text-[11px] text-muted-foreground">
          展示 {{ visibleItems.length }} / {{ plan.items.length }} 条；筛选与排序只影响展示，
          提交范围是「已勾选」的 {{ pickedItems.length }} 本。
        </span>
      </div>

      <div v-if="!plan.items.length" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        没有需要整理的书（要么已经符合 Komga 结构，要么判不出系列）。
      </div>

      <div v-else-if="!visibleItems.length" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        当前筛选下没有条目 —— 清空搜索或取消「只看冲突」。
      </div>

      <div v-else class="max-h-[460px] overflow-auto">
        <table class="w-full text-[12px]">
          <thead class="sticky top-0 bg-card text-left text-muted-foreground">
            <tr>
              <th class="w-8 px-3 py-2" />
              <th class="px-3 py-2">系列 / 书名</th>
              <th class="px-3 py-2">当前位置</th>
              <th class="px-3 py-2">整理后</th>
              <th class="w-32 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="it in visibleItems"
              :key="it.old"
              class="border-t border-border/60"
              :class="it.conflict ? 'bg-destructive/5' : ''"
            >
              <td class="px-3 py-2 align-top">
                <input
                  type="checkbox"
                  class="h-4 w-4 cursor-pointer accent-primary disabled:cursor-not-allowed"
                  :checked="picked.has(it.old)"
                  :disabled="it.conflict"
                  @change="togglePick(it.old)"
                />
              </td>
              <td class="px-3 py-2 align-top">
                <div class="text-foreground">{{ it.title }}</div>
                <div class="text-[11px] text-muted-foreground">
                  {{ it.series }}<span v-if="it.index"> · 第 {{ it.index }} 卷</span>
                  <span v-if="it.author"> · {{ it.author }}</span>
                </div>
              </td>
              <td class="px-3 py-2 align-top font-mono text-[11px] text-muted-foreground">{{ it.old }}</td>
              <td class="px-3 py-2 align-top font-mono text-[11px] text-foreground">{{ it.new }}</td>
              <td class="px-3 py-2 align-top text-[11px]">
                <span v-if="it.conflict" class="text-destructive">{{ it.reason }}</span>
                <span v-else-if="it.id_changes" class="text-amber-600 dark:text-amber-400">换 id · 迁数据</span>
                <span v-else class="text-muted-foreground">仅挪目录</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        <div class="mb-1.5 font-medium text-foreground">Komga 的库结构约定（决定了上面的规则）</div>
        <ul class="ml-4 list-disc space-y-1">
          <li><b>一层系列目录</b>：<code class="font-mono">库根/系列名/书文件</code>。Komga
            <b>不会递归</b>系列文件夹的子目录 —— 所以本项目最多建一层，不会更深。</li>
          <li><b>一个目录 = 一个系列</b>，目录内多个文件 = 该系列的多个卷。</li>
          <li><b>卷号从文件名解析</b>：<code class="font-mono">系列 #1.cbz</code> 最稳，
            所以整理时会把文件名统一成这个形式。</li>
          <li>把 <code class="font-mono">OUTPUT_DIR</code> 直接作为 Komga 库根目录即可；
            Komga 只读扫描，不会改动文件。</li>
        </ul>
      </div>
    </Card>

    <!-- 兼容服务端：让第三方 Komga 客户端直接连本应用（不必安装 Komga） -->
    <Card class="mt-4" padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="text-[13px] font-medium text-foreground">Komga 兼容服务端</span>
            <span v-if="komga.enabled" class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400">
              已开启
            </span>
            <span v-else class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">未开启</span>
          </div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启后，第三方 Komga 客户端（Mihon / Panels / 官方 App）把服务器地址填成本应用即可：
            浏览书库、读漫画与 PDF、下载 EPUB、双向同步阅读进度
          </div>
        </div>
        <Button size="sm" :variant="komga.enabled ? 'ghost' : 'primary'" :disabled="saving || !cfg"
                @click="setVal('komga.enabled', !komga.enabled); saveSection('komga')">
          {{ komga.enabled ? '关闭' : '开启' }}
        </Button>
      </div>

      <!-- 未开启时地址与凭据只是先填好备用，如实说明，避免误以为此刻已能连上 -->
      <div v-if="!komga.enabled" class="border-b border-border bg-muted/40 px-4 py-2 text-[11.5px] text-muted-foreground">
        当前<strong>未开启</strong>：下面的地址与凭据只是先填好备用，客户端此刻连不上；点上方「开启」后立即生效。
      </div>

      <div class="border-b border-border px-4 py-3.5" :class="komga.enabled ? '' : 'opacity-55'">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">服务器地址</div>
        <div class="flex flex-wrap items-center gap-2">
          <code class="flex-1 truncate rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground">
            {{ serverUrl }}
          </code>
          <Button size="sm" @click="copyServer">{{ copiedServer ? '已复制' : '复制' }}</Button>
        </div>
        <div class="mt-1.5 text-[11.5px] text-muted-foreground">
          客户端里填这个地址即可（它会自己拼 <code class="font-mono">/api/v1</code>）
        </div>
      </div>

      <div class="border-b border-border px-4 py-3.5" :class="komga.enabled ? '' : 'opacity-55'">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">凭据</div>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[12px] text-muted-foreground">用户名（密码 = 登录 PIN）</span>
            <input :value="val('komga.username')" type="text"
                   class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
                   @input="setVal('komga.username', ($event.target as HTMLInputElement).value)" />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-muted-foreground">
              API Key（可选，掩码表示已设置；清空即删除）
            </span>
            <input :value="val('komga.api_key')" type="password" placeholder="未设置"
                   class="w-full rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
                   @input="setVal('komga.api_key', ($event.target as HTMLInputElement).value)" />
          </label>
        </div>
        <div class="mt-2 flex items-center gap-2">
          <Button size="sm" variant="primary" :disabled="saving" @click="saveSection('komga')">保存</Button>
          <span class="text-[11.5px] text-muted-foreground">
            三种认证都支持：HTTP Basic、<code class="font-mono">X-API-Key</code> 头、会话 cookie
          </span>
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">客户端里怎么填</div>
        <ol class="ml-4 list-decimal space-y-1 text-[12.5px] text-muted-foreground">
          <li>在客户端里选「Komga」这类源，服务器地址填上面的地址</li>
          <li>用户名 / 密码填上面的用户名与登录 PIN（或用 API Key）</li>
          <li>漫画与 PDF 走<strong>页面流</strong>在线阅读；EPUB 走下载（也可用 WebPub manifest）</li>
        </ol>
        <p class="mt-2 text-[11.5px] text-muted-foreground">
          阅读进度双向同步：客户端读到第几页 ↔ 本项目详情页的进度；EPUB 用 locator（章节 + 百分比）。
          实测通过：Mihon/Panels 所需的 <code class="font-mono">/api/v1/libraries</code>、
          <code class="font-mono">/series</code>、<code class="font-mono">/books</code>、
          <code class="font-mono">/pages</code>、<code class="font-mono">/read-progress</code> 均已按 Komga 的分页壳与字段名对齐；
          书库维度也已打通 —— 客户端点进某个书库只看到该库的内容，系列上还能直接标「全部已读」。
        </p>
        <p class="mt-2 text-[11.5px] text-muted-foreground">
          想让某个书库<strong>不出现在</strong>客户端里（例如只给孩子设备看的那台）？去「设置 → 书库管理 → 每库设置」
          关掉它的「对 Komga 暴露」—— 关掉后它不进书库列表，直连它的系列 / 书籍地址也一并 404。
        </p>
        <p class="mt-2 text-[11.5px] text-amber-600 dark:text-amber-400">
          有声书库不会出现在 Komga 客户端里：Komga 没有音频模型，硬塞进去只会得到打不开的坏条目。
          要听有声书请用应用内的播放器或 OPDS。
        </p>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="Komga"
      :groups="['SERVER', 'LIBRARIES', 'SYNC']"
      :items="[
        '从 Komga 拉取书目 / 下载入库（需 Komga REST 客户端）',
        '与已有 Komga 服务器双向同步（本项目已能充当服务端，但不做客户端）',
        'HTTP/2 与 WebSocket 那类实时推送（客户端会回落到轮询）',
      ]"
      note="已实现两侧：①输出侧——输出布局开关（output.layout）+ 既有库整理（会改名时自动迁移阅读数据）；②兼容服务端——第三方 Komga 客户端可直接连本应用，支持 Basic / X-API-Key / 会话认证、分页壳、系列与书籍列表（可按书库过滤，老客户端的 GET 端点同样生效）、封面、CBZ/CBR 与 PDF 页面流、EPUB 下载与 manifest、阅读进度双向同步，以及系列级「全部已读 / 全部未读」（只把百分比顶到 100，不清除读者位置）。有声书库不进 Komga（Komga 没有音频模型）。"
    />
  </div>
</template>
