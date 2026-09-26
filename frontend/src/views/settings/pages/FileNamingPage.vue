<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { RENAME_RECIPES, RENAME_SCOPES, RENAME_TOKENS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type NamingPlan } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * LIBRARY → File Naming（`/settings/library/file-naming`）
 *
 * 真实实现：把命名规则（pattern + 格式筛选）**存到服务端**（config.naming，走 settings.json 覆盖层）。
 *
 * ⚠️ 第 28 期起规则的口径是**成品副本名**（改名不再动源文件名）——「批量重命名」工具已并入
 * 刮削面板的「命名规则」区块，本页因此只负责**全局**规则的编辑与预览：
 * 每库覆写、预览、一键重出版都在「工具 → 转换日志 → 刮削」里（同一份规则，只有一个写点管全局）。
 *
 * 上游的 13 个 token / 7 个修饰符 / STRUCTURE / 元数据缺失降级预览，本项目**不支持**，只读标注。
 */

const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

const plan = ref<NamingPlan | null>(null)
const previewing = ref(false)

const pattern = computed(() => String(val('naming.pattern') ?? ''))
const scope = computed(() => String(val('naming.scope') ?? 'all'))

const previewItems = computed(() => (plan.value?.items ?? []).slice(0, 5))
const conflictCount = computed(() => (plan.value?.items ?? []).filter((i) => i.conflict).length)

function applyRecipe(p: string): void {
  setVal('naming.pattern', p)
  plan.value = null
}

async function runPreview(): Promise<void> {
  if (!pattern.value.trim()) {
    ui.toast('请先填写命名规则')
    return
  }
  previewing.value = true
  try {
    // 传当前草稿而非已保存值：所见即所得。不带 library_id = 用全局规则算全部书库的副本名
    plan.value = await api.namingPreview({ pattern: pattern.value, scope: scope.value })
    if (!plan.value.items.length) ui.toast('还没有已出版的副本可供对照')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '预览失败')
  } finally {
    previewing.value = false
  }
}

async function save(): Promise<void> {
  const ok = await saveSection('naming')
  if (ok) plan.value = null
}

onMounted(() => loadConfig())
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">文件命名</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">File Naming</span>
      <span class="text-[11.5px] text-muted-foreground">
        成品<strong>副本</strong>的命名规则（刮削出版与「按此规则重出版」都用它；源文件名不受影响）
      </span>
      <Button size="sm" variant="primary" class="ml-auto" :disabled="saving" @click="save">保存</Button>
    </div>

    <Card padding="none" class="mb-4">
      <template v-if="cfg">
        <div class="border-b border-border px-4 py-3">
          <div class="mb-1.5 text-[13px] font-medium text-foreground">命名规则</div>
          <div class="mb-2 text-[11.5px] text-muted-foreground">
            把占位符拼成文件名模板；扩展名由后端自动追加在末尾，无需手写。
            这里改的是<strong>全局</strong>规则；某个库想用别的规则，去「工具 → 转换日志 → 刮削 →
            命名规则」改该库的覆写。
          </div>
          <div class="flex flex-wrap items-center gap-2">
            <input
              :value="pattern"
              type="text"
              placeholder="{index}. {author} - {title}"
              aria-label="命名规则"
              class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-3 font-mono text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
              @input="setVal('naming.pattern', ($event.target as HTMLInputElement).value); plan = null"
              @keydown.enter="runPreview"
            >
            <select
              :value="scope"
              aria-label="格式筛选"
              class="h-8 shrink-0 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
              @change="setVal('naming.scope', ($event.target as HTMLSelectElement).value); plan = null"
            >
              <option v-for="s in RENAME_SCOPES" :key="s.value" :value="s.value">{{ s.label }}</option>
            </select>
            <Button :disabled="previewing" @click="runPreview">预览生效结果</Button>
          </div>
        </div>

        <!-- 配方 -->
        <div class="border-b border-border px-4 py-3">
          <div class="mb-2 text-[13px] font-medium text-foreground">配方</div>
          <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            <button
              v-for="r in RENAME_RECIPES"
              :key="r.name"
              type="button"
              class="cursor-pointer rounded-md border px-3 py-2 text-left transition-colors"
              :class="pattern === r.pattern ? 'border-ring bg-muted' : 'border-border hover:bg-muted/60'"
              @click="applyRecipe(r.pattern)"
            >
              <div class="text-[12.5px] font-medium text-foreground">{{ r.name }}</div>
              <div class="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{{ r.pattern }}</div>
              <div class="mt-1 text-[11px] text-muted-foreground">{{ r.desc }}</div>
            </button>
          </div>
        </div>

        <!-- 占位符 -->
        <div class="px-4 py-3">
          <div class="mb-2 text-[13px] font-medium text-foreground">
            可用占位符（{{ RENAME_TOKENS.length }} 个）
          </div>
          <div class="space-y-1.5">
            <div v-for="t in RENAME_TOKENS" :key="t.token" class="flex items-baseline gap-3">
              <code class="w-20 shrink-0 font-mono text-[12px] text-foreground">{{ t.token }}</code>
              <span class="min-w-0 flex-1 text-[11.5px] text-muted-foreground">{{ t.desc }}</span>
            </div>
          </div>
        </div>
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <!-- 预览结果 -->
    <Card v-if="plan && plan.items.length" padding="none" class="mb-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">生效预览</h3>
        <span class="text-[11.5px] text-muted-foreground">
          已出版 {{ plan.stats.total }} 本，会改名 {{ plan.stats.changed }} 本<template v-if="conflictCount">，{{ conflictCount }} 本落点冲突</template>
        </span>
        <span class="ml-auto text-[11px] text-muted-foreground">仅预览，不会改动任何文件</span>
      </div>
      <div
        v-for="p in previewItems"
        :key="p.book_id"
        class="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-[12px] last:border-b-0"
      >
        <span class="min-w-0 flex-1 truncate text-muted-foreground" :title="p.old_rel">{{ p.old_rel }}</span>
        <Icon name="arrowRight" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span class="min-w-0 flex-1 truncate font-medium" :class="p.conflict ? 'text-destructive' : 'text-foreground'" :title="p.new_rel">
          {{ p.new_rel }}
        </span>
      </div>
      <div class="flex flex-wrap items-center gap-2 px-4 py-3">
        <span class="text-[11.5px] text-muted-foreground">
          <template v-if="plan.items.length > 5">还有 {{ plan.items.length - 5 }} 项未显示；</template>
          预览与落盘共用服务端的同一份展开逻辑，所以「新名」就是重出版后的落盘名。
        </span>
        <RouterLink to="/tools/logs?tab=scrape" class="ml-auto">
          <Button size="sm">去刮削面板重出版</Button>
        </RouterLink>
      </div>
    </Card>

    <p v-else class="mb-4 text-[11px] text-muted-foreground">
      保存后，<RouterLink to="/tools/logs?tab=scrape" class="underline">工具 → 转换日志 → 刮削</RouterLink>
      里的「命名规则」区块会默认载入这条规则，并可按它一键重出版副本。
    </p>

    <SettingsUnsupportedCard
      label="File Naming"
      :groups="['TOKENS', 'MODIFIERS', 'STRUCTURE', 'OR START FROM A RECIPE', 'IF METADATA IS MISSING']"
      :items="[
        '上游 13 个 token 中本项目缺 4 个：{subtitle} {isbn} {library} {originalFilename}',
        'token 名不同：本项目是 {author} / {series_index} / {ext}，上游是 {authors} / {seriesIndex} / {extension}',
        '7 个修饰符：:first :sort :initial :fixed2 :max3 :upper :lower',
        '4 类结构语法：optional（可选段）/ fallback（回退）/ folder（目录分隔）/ or（或）',
        '组织模式：Folder as Book / File as Book（本项目为单一成品目录）',
        '元数据缺失时的降级预览（No series / No year / No author 三种）',
        'Cross-platform path sanitization（本项目固定做非法字符清理）',
      ]"
      note="本项目支持 9 个占位符（书名 / 作者 / 系列 / 系列序号 / 卷号 / 出版年 / 出版社 / 语言 / 扩展名）与朴素字符串替换，没有修饰符与结构语法；上游的目录层级（<...> 分段）也不支持 —— 本项目成品目录是扁平的。规则只作用于**副本名**（刮削出版时写入成品目录），源文件名永不改动。"
    />
  </div>
</template>
