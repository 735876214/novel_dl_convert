<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, type CalibrePreview, type CalibreRegisterResult } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * 外部书库的**只读登记**导入（第 228 期）。
 *
 * ## 它做什么
 *
 * 读 Calibre 的 `metadata.db`，把它的元数据（书名 / 作者 / 系列 / ISBN …）写成
 * 本项目的**覆盖层**。那些书**就地引用**被本项目扫到 —— **零拷贝**。
 *
 * ## 它**不**做什么（范围刻意很小）
 *
 * - **不复制文件、不移动、不删除**（本项目的书库模型就是「就地引用 + 来源根」）；
 * - **不导**对方应用的用户 / 阅读进度 / 评分（那是多人模型的东西，本项目单用户）；
 * - **不装 Calibre 运行时**（只是读一个 SQLite 文件）。
 *
 * ## 前提（顺序不能反）
 *
 * ① Calibre 那个目录**已经**登记成书库的来源根 ⇒ ② 本项目扫到那些文件
 * ⇒ ③ 在这里登记元数据。**没扫到就登记不了** —— 界面会如实说明。
 */
const ui = useUiStore()
const library = useLibraryStore()

/** Calibre 的 `metadata.db` 路径（服务器上的路径） */
const dbPath = ref('')
/** Calibre 书库根目录（服务器上的路径） */
const rootPath = ref('')
/** 目标书库（那个目录已经是它的来源根） */
const libraryId = ref('')

const preview = ref<CalibrePreview | null>(null)
const result = ref<CalibreRegisterResult | null>(null)
const busy = ref('')
const error = ref('')

const libs = computed(() => library.libraryEntities)

onMounted(async () => {
  await library.loadLibraries()
  if (libs.value.length) libraryId.value = libs.value[0]?.id ?? ''
})

/** 能不能预览：三个输入都得有 */
const canPreview = computed(
  () => Boolean(dbPath.value.trim() && rootPath.value.trim()) && !busy.value,
)

async function runPreview(): Promise<void> {
  if (!canPreview.value) return
  busy.value = 'preview'
  error.value = ''
  result.value = null
  try {
    preview.value = await api.calibrePreview(dbPath.value.trim(), rootPath.value.trim())
  } catch (e) {
    preview.value = null
    error.value = e instanceof Error ? e.message : '读取失败'
  } finally {
    busy.value = ''
  }
}

async function runRegister(): Promise<void> {
  if (!canPreview.value || !libraryId.value || busy.value) return
  busy.value = 'register'
  error.value = ''
  try {
    result.value = await api.calibreRegister({
      library_id: libraryId.value,
      db_path: dbPath.value.trim(),
      root: rootPath.value.trim(),
    })
    const r = result.value
    ui.toast(r.ok
      ? `已登记 ${r.written} 个字段（${r.matched} 本）`
      : `登记了 ${r.matched} 本，跳过 ${r.skipped} 本`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登记失败'
  } finally {
    busy.value = ''
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">外部书库登记</h2>
      <span class="text-[11.5px] text-muted-foreground">
        把 Calibre 书库的元数据登记进本项目（只读：不复制文件、不动源、不导进度）
      </span>
    </div>

    <Card padding="sm">
      <div class="flex flex-col gap-3">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">Calibre 的 metadata.db（服务器路径）</span>
          <input
            v-model="dbPath"
            type="text"
            aria-label="metadata.db 路径"
            placeholder="/volume1/Calibre Library/metadata.db"
            class="h-8 rounded-md border border-border bg-muted px-2.5 font-mono text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
          >
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">Calibre 书库根目录（服务器路径）</span>
          <input
            v-model="rootPath"
            type="text"
            aria-label="书库根目录"
            placeholder="/volume1/Calibre Library"
            class="h-8 rounded-md border border-border bg-muted px-2.5 font-mono text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
          >
        </label>

        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">
            目标书库（那个目录应当已经是它的**来源根**）
          </span>
          <select
            v-model="libraryId"
            aria-label="目标书库"
            class="h-8 rounded-md border border-border bg-muted px-2 text-[12px] text-foreground outline-none focus:border-ring"
          >
            <option v-for="l in libs" :key="l.id" :value="l.id">{{ l.name }}</option>
          </select>
          <span class="text-[10.5px] text-muted-foreground">
            顺序：先把 Calibre 目录登记成这个库的来源根 → 扫描扫到书 → 再来这里登记元数据
          </span>
        </label>

        <div class="flex flex-wrap items-center gap-2">
          <Button size="sm" :disabled="!canPreview" @click="runPreview">
            {{ busy === 'preview' ? '读取中…' : '预览' }}
          </Button>
          <Button
            size="sm"
            variant="primary"
            :disabled="!canPreview || !libraryId || busy === 'register'"
            @click="runRegister"
          >
            {{ busy === 'register' ? '登记中…' : '登记元数据' }}
          </Button>
          <span v-if="error" class="text-[12px] text-destructive">{{ error }}</span>
        </div>
      </div>
    </Card>

    <Card v-if="preview" padding="sm">
      <div class="mb-2 text-[12.5px] font-medium text-foreground">
        读到 {{ preview.total }} 本；可登记 {{ preview.plan.items.length }} 本
        <span v-if="preview.plan.skipped.length" class="text-muted-foreground">
          （{{ preview.plan.skipped.length }} 本登记不了）
        </span>
      </div>
      <p v-for="w in preview.warnings" :key="w" class="text-[11.5px] text-warning">{{ w }}</p>
      <p v-for="w in preview.plan.warnings" :key="`p-${w}`" class="text-[11.5px] text-warning">{{ w }}</p>

      <div v-if="preview.plan.items.length" class="mt-2 max-h-64 overflow-y-auto">
        <table class="w-full text-[11.5px]">
          <thead class="text-left text-muted-foreground">
            <tr>
              <th class="py-1 pr-2 font-normal">书名</th>
              <th class="py-1 pr-2 font-normal">作者</th>
              <th class="py-1 pr-2 font-normal">系列</th>
              <th class="py-1 font-normal">路径</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="it in preview.plan.items.slice(0, 200)" :key="it.path" class="border-t border-border/60">
              <td class="py-1 pr-2 text-foreground">{{ it.title || '（无）' }}</td>
              <td class="py-1 pr-2 text-foreground">{{ it.author || '—' }}</td>
              <td class="py-1 pr-2 text-foreground">
                {{ it.series || '—' }}<span v-if="it.series_index"> #{{ it.series_index }}</span>
              </td>
              <td class="py-1 font-mono text-muted-foreground">{{ it.path }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="preview.plan.items.length > 200" class="mt-1 text-[11px] text-muted-foreground">
          只列了前 200 条（共 {{ preview.plan.items.length }} 条）。
        </p>
      </div>

      <div v-if="preview.plan.skipped.length" class="mt-3 border-t border-border pt-2">
        <div class="text-[11.5px] font-medium text-foreground">登记不了的</div>
        <p
          v-for="s in preview.plan.skipped.slice(0, 50)"
          :key="s.path"
          class="text-[11px] text-muted-foreground"
        >
          「{{ s.title }}」—— {{ s.reason }}
        </p>
      </div>
    </Card>

    <Card v-if="result" padding="sm">
      <div class="text-[12.5px] font-medium text-foreground">
        登记结果：匹配 {{ result.matched }} 本 / 写入 {{ result.written }} 个字段
        <span v-if="result.skipped" class="text-muted-foreground">/ 跳过 {{ result.skipped }} 本</span>
      </div>
      <p v-for="w in result.warnings" :key="w" class="mt-1 text-[11.5px] text-warning">{{ w }}</p>
    </Card>

    <EmptyState
      v-if="!preview"
      icon="upload"
      dashed
      title="先填上面三个路径"
      desc="填好后点「预览」，会先列出读到多少本、能登记多少本；确认无误再点「登记元数据」。"
    />
  </div>
</template>
