<script setup lang="ts">
/**
 * 批量编辑元数据（第 157 期）：书架上选好几本 → 只填要统一的字段 → 逐本回执。
 *
 * 三条口径：
 *  1. **留空 = 不修改**（不是清空）。想批量清空某个字段目前没有入口 ——
 *     清空是 `null` 语义，误点「全选 + 清空作者」是不可逆的破坏，故不做；
 *  2. 真正的校验与写入在服务端，且**复用单书编辑那一处**（`/api/books/batch-metadata`
 *     逐本调 `api_set_book_metadata`）—— 前端只负责收集非空字段；
 *  3. 某本失败不连累其它本，失败原因逐条显示（不吞错、不写「部分成功」了事）。
 */
import { computed, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import { api, type BatchMetadataResult, type BookMetadataWriteFields } from '@/lib/api'
import { parseTokenList } from '@/lib/tags'

const props = defineProps<{
  open: boolean
  bookIds: string[]
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'done'): void }>()

/** 与本页其它表单一致的输入框样式（这里只有本组件用，故就近放） */
const INPUT =
  'h-8 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring'

const author = ref('')
const series = ref('')
const publisher = ref('')
const language = ref('')
const date = ref('')
const tagsText = ref('')
const busy = ref(false)
const error = ref('')
const result = ref<BatchMetadataResult | null>(null)

function reset(): void {
  author.value = ''
  series.value = ''
  publisher.value = ''
  language.value = ''
  date.value = ''
  tagsText.value = ''
  error.value = ''
  result.value = null
}

watch(
  () => props.open,
  (o) => {
    if (o) reset()
  },
)

/** 只收集**非空**字段：留空表示这本不参与该字段（绝不把空串当「撤销覆盖」发出去）。 */
const fields = computed<BookMetadataWriteFields>(() => {
  const f: Record<string, string | string[]> = {}
  if (author.value.trim()) f.author = author.value.trim()
  if (series.value.trim()) f.series = series.value.trim()
  if (publisher.value.trim()) f.publisher = publisher.value.trim()
  if (language.value.trim()) f.language = language.value.trim()
  if (date.value.trim()) f.date = date.value.trim()
  const tags = parseTokenList(tagsText.value)
  if (tags.length) f.tags = tags
  return f as BookMetadataWriteFields
})

const fieldCount = computed(() => Object.keys(fields.value).length)

async function apply(): Promise<void> {
  if (!fieldCount.value || busy.value) return
  busy.value = true
  error.value = ''
  try {
    result.value = await api.batchSetMetadata(props.bookIds, fields.value)
    emit('done')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    busy.value = false
  }
}

const failures = computed(() => (result.value?.results ?? []).filter((r) => !r.ok))
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 grid place-items-center bg-black/35 p-4"
    @click.self="emit('close')"
  >
    <div class="max-h-[88vh] w-[min(38rem,94vw)] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-2xl">
      <div class="flex items-start gap-2">
        <h3 class="font-serif text-[17px] font-semibold text-foreground">批量编辑元数据</h3>
        <span class="mt-1 text-[11.5px] text-muted-foreground">已选 {{ bookIds.length }} 本</span>
        <Button size="sm" variant="ghost" class="ml-auto" @click="emit('close')">关闭</Button>
      </div>
      <p class="mt-1 text-[12px] leading-relaxed text-muted-foreground">
        <strong>留空的字段不会被修改。</strong>改动只存应用数据库、不写回书文件；
        每本书的结果逐条列出，某一本失败不影响其它本。
      </p>

      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">作者</span>
          <input v-model="author" type="text" :class="INPUT" placeholder="留空 = 不修改" :disabled="busy">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">系列</span>
          <input v-model="series" type="text" :class="INPUT" placeholder="留空 = 不修改" :disabled="busy">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">出版社</span>
          <input v-model="publisher" type="text" :class="INPUT" placeholder="留空 = 不修改" :disabled="busy">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">语言</span>
          <input v-model="language" type="text" :class="INPUT" placeholder="如 zh（留空 = 不修改）" :disabled="busy">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">出版日期</span>
          <input v-model="date" type="text" :class="INPUT" placeholder="如 2024-01-02（留空 = 不修改）" :disabled="busy">
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">题材（顿号或逗号分隔）</span>
          <input v-model="tagsText" type="text" :class="INPUT" placeholder="如 科幻、经典" :disabled="busy">
        </label>
      </div>

      <div v-if="result" class="mt-4 rounded-md border border-border p-2.5">
        <div class="text-[12px] font-medium text-foreground">
          已写入 {{ result.saved }} 本<span v-if="result.failed">，{{ result.failed }} 本失败</span>
        </div>
        <ul v-if="failures.length" class="mt-1.5 space-y-1">
          <li
            v-for="f in failures"
            :key="f.id"
            class="text-[11.5px] leading-relaxed text-destructive"
          >
            {{ f.id }}：{{ f.error || '失败' }}
          </li>
        </ul>
        <div v-else class="mt-1 text-[11.5px] text-muted-foreground">全部成功。</div>
      </div>
      <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>

      <div class="mt-4 flex items-center justify-end gap-2">
        <span class="mr-auto text-[11.5px] text-muted-foreground">
          {{ fieldCount ? `将修改 ${fieldCount} 个字段` : '至少填一个字段' }}
        </span>
        <Button size="sm" variant="ghost" :disabled="busy" @click="emit('close')">取消</Button>
        <Button size="sm" variant="primary" :disabled="busy || !fieldCount" @click="apply">
          {{ busy ? '保存中…' : `应用到 ${bookIds.length} 本` }}
        </Button>
      </div>
    </div>
  </div>
</template>
