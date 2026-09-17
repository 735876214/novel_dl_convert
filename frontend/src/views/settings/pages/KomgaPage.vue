<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type KomgaLayoutPlan } from '@/lib/api'
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

async function preview(): Promise<void> {
  busy.value = true
  try {
    const p = await api.komgaLayoutPreview()
    plan.value = p
    // 默认勾选全部无冲突条目：整理是个「我全都要」的动作
    picked.value = new Set(p.items.filter((i) => !i.conflict).map((i) => i.old))
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '预览失败')
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
            开启后，**有系列**的书按 <code class="font-mono">系列名/系列名 #N.ext</code> 落盘；
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
          判不出时从**文件名**推断（<code class="font-mono">系列 第01卷</code> /
          <code class="font-mono">系列 #1</code> / <code class="font-mono">系列 (01)</code> 这类）；
          两者都判不出的书原地不动 —— 凭空造一个系列名比平铺更糟。
        </div>
        <Button size="sm" :disabled="busy" @click="preview">
          {{ busy ? '处理中…' : '预览整理方案' }}
        </Button>
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

      <div v-if="!plan.items.length" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
        没有需要整理的书（要么已经符合 Komga 结构，要么判不出系列）。
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
              v-for="it in plan.items"
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

    <SettingsUnsupportedCard
      label="Komga"
      :groups="['SERVER', 'LIBRARIES', 'SYNC']"
      :items="[
        '从 Komga 拉取书目 / 下载入库（需 Komga REST 客户端）',
        '与 Komga 双向同步阅读进度',
        '按 Komga 库分别输出（本项目单一 OUTPUT_DIR）',
      ]"
      note="本项目已实现「输出侧」：输出布局开关（output.layout）+ 既有库整理（预览 → 应用，改名的书自动迁移阅读进度/批注/评分/收藏）。"
    />
  </div>
</template>
