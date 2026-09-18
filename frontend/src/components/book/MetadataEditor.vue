<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type BookMetadata, type BookMetadataFields } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 单书元数据编辑（详情页第 5 个标签）。
 *
 * 元数据分层原则（第 8 期）：生效值 = 用户覆盖(override) > 在线抓取(online) > OPF 原值(opf)。
 *  - 编辑保存：与 OPF 原值不同的字段记入用户覆盖，再抓取不冲掉；
 *  - 已覆盖的字段显示「已本地修改」徽标 + 「恢复在线」按钮（撤销覆盖并写回在线值）。
 */
const props = defineProps<{ bookId: string }>()
const emit = defineEmits<{ saved: [] }>()

const ui = useUiStore()
const meta = ref<BookMetadata | null>(null)
const loading = ref(true)
const saving = ref(false)
const restoring = ref(false)
const form = ref<BookMetadataFields | null>(null)
const changed = ref<string[]>([])
const tagText = ref('')

const FIELD_LABELS: Record<keyof BookMetadataFields, string> = {
  title: '书名',
  author: '作者',
  series: '系列',
  series_index: '系列序号',
  date: '出版年',
  publisher: '出版社',
  language: '语言',
  description: '简介',
  isbn: 'ISBN',
  tags: '题材',
}

/** 界面上的展示顺序（后端返回是按字母序的字典，直接遍历会很乱） */
const TEXT_FIELDS: (keyof BookMetadataFields)[] = [
  'title', 'author', 'series', 'series_index', 'date', 'publisher', 'language', 'isbn',
]

async function load(): Promise<void> {
  loading.value = true
  changed.value = []
  try {
    meta.value = await api.bookMetadata(props.bookId)
    form.value = { ...(meta.value?.fields as BookMetadataFields) }
    tagText.value = (form.value.tags || []).join('、')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '元数据加载失败')
    meta.value = null
  }
  loading.value = false
}

onMounted(load)
watch(() => props.bookId, load)

const editable = computed(() => meta.value?.editable === true)

/** 是否有任意字段被用户本地覆盖（决定「恢复全部为在线」是否可用） */
const hasOverrides = computed(() =>
  !!meta.value && Object.values(meta.value.meta).some((m) => m.overridden),
)

/** 是否有未保存的改动（与加载时的生效值比对） */
const dirty = computed(() => {
  if (!meta.value || !form.value) return false
  const a = meta.value.fields
  const b = { ...form.value, tags: parseTags() }
  return (Object.keys(a) as (keyof BookMetadataFields)[]).some((k) =>
    k === 'tags' ? JSON.stringify(a.tags) !== JSON.stringify(b.tags) : String(a[k]) !== String(b[k]),
  )
})

function fmt(v: string | string[]): string {
  return Array.isArray(v) ? v.join('、') : String(v ?? '')
}

function metaState(k: keyof BookMetadataFields) {
  return meta.value?.meta?.[k]
}

/** 已覆盖字段的「在线建议值」提示文案 */
function onlineText(k: keyof BookMetadataFields): string {
  const s = metaState(k)
  if (s?.overridden) {
    const o = fmt(s.online)
    return o ? `在线：${o}` : '（无在线建议，恢复后将回到 OPF 原值）'
  }
  return ''
}

function parseTags(): string[] {
  return tagText.value
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function save(): Promise<void> {
  if (!form.value || !meta.value) return
  saving.value = true
  try {
    const fields = { ...form.value, tags: parseTags() }
    const r = await api.setBookMetadata(props.bookId, fields)
    changed.value = r.changed
    if (r.unknown.length) {
      ui.toast(`已保存；不支持的字段已忽略：${r.unknown.join('、')}`)
    } else {
      ui.toast(r.changed.length ? `已保存，实际改动 ${r.changed.length} 项` : '没有实际改动')
    }
    // 用服务端回读的值刷新表单与分层明细（后端会做规整，如 3.00 → 3）
    meta.value = { ...meta.value, fields: { ...r.fields }, meta: { ...r.meta } }
    form.value = { ...r.fields }
    tagText.value = (r.fields.tags || []).join('、')
    emit('saved')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function restoreFields(fields: string[]): Promise<void> {
  if (!meta.value || !fields.length) return
  restoring.value = true
  try {
    const r = await api.revertBookMetadata(props.bookId, fields)
    meta.value = { ...meta.value, fields: { ...r.fields }, meta: { ...r.meta } }
    form.value = { ...r.fields }
    tagText.value = (r.fields.tags || []).join('、')
    ui.toast(`已恢复 ${r.recovered.length} 个字段为在线值`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    restoring.value = false
  }
}

function restoreOne(k: keyof BookMetadataFields): void {
  void restoreFields([k])
}

function restoreAll(): void {
  const fields = meta.value
    ? Object.keys(meta.value.meta).filter((f) => meta.value!.meta[f]?.overridden)
    : []
  void restoreFields(fields)
}

const INPUT_CLS =
  'h-8 w-full rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card'
</script>

<template>
  <div>
    <div v-if="loading" class="py-16 text-center text-[13px] text-muted-foreground">加载中…</div>

    <template v-else-if="meta && form">
      <Card v-if="!editable" padding="sm" class="mb-3">
        <div class="flex gap-2 text-[12px] text-muted-foreground">
          <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            该书的格式是 <span class="font-mono">{{ meta.format || '未知' }}</span>。
            元数据编辑只支持 EPUB —— 其它格式没有可改写的 OPF，因此这里只能查看。
          </span>
        </div>
      </Card>

      <Card padding="none" class="mb-3">
        <div class="border-b border-border px-4 py-3">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-[13px] font-semibold text-foreground">编辑元数据</h3>
            <span class="font-mono text-[11px] text-muted-foreground">{{ meta.name }}</span>
            <span v-if="dirty" class="rounded bg-warning/14 px-1.5 py-0.5 text-[10.5px] text-warning">有未保存的改动</span>
          </div>
          <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
            直接写入 EPUB 内嵌的 OPF，改完立即被书库扫描读到。<strong>不会改文件名</strong>。
            在线抓取默认优先覆盖本地；你手动改过的字段会被保护（标「已本地修改」），再抓取也不冲掉，可随时「恢复在线」。
          </p>
        </div>

        <div class="grid grid-cols-1 gap-x-4 px-4 py-3 sm:grid-cols-2">
          <label
            v-for="k in TEXT_FIELDS"
            :key="k"
            class="flex flex-col gap-1 border-b border-border/60 py-2.5"
          >
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              {{ FIELD_LABELS[k] }}
              <span
                v-if="meta.meta[k]?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
            </span>
            <input v-model="form[k] as string" type="text" :disabled="!editable" :class="INPUT_CLS">
            <div
              v-if="meta.meta[k]?.overridden"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                type="button"
                :disabled="!editable || restoring"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne(k)"
              >
                ↺ 恢复在线
              </button>
              <span class="text-muted-foreground">{{ onlineText(k) }}</span>
            </div>
          </label>

          <label class="flex flex-col gap-1 border-b border-border/60 py-2.5 sm:col-span-2">
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              题材（用「、」或逗号分隔，保存时自动去重）
              <span
                v-if="meta.meta.tags?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
            </span>
            <input v-model="tagText" type="text" :disabled="!editable" :class="INPUT_CLS" placeholder="科幻 · 小说">
            <div
              v-if="meta.meta.tags?.overridden"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                type="button"
                :disabled="!editable || restoring"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne('tags')"
              >
                ↺ 恢复在线
              </button>
              <span class="text-muted-foreground">{{ onlineText('tags') }}</span>
            </div>
          </label>

          <label class="flex flex-col gap-1 py-2.5 sm:col-span-2">
            <span class="flex items-center gap-2 text-[11.5px] text-muted-foreground">
              简介
              <span
                v-if="meta.meta.description?.overridden"
                class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
              >已本地修改</span>
            </span>
            <textarea
              v-model="form.description"
              rows="5"
              :disabled="!editable"
              class="w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
            />
            <div
              v-if="meta.meta.description?.overridden"
              class="mt-1 flex flex-wrap items-center gap-2 text-[11px]"
            >
              <button
                type="button"
                :disabled="!editable || restoring"
                class="cursor-pointer rounded text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
                @click="restoreOne('description')"
              >
                ↺ 恢复在线
              </button>
              <span class="text-muted-foreground">{{ onlineText('description') }}</span>
            </div>
          </label>
        </div>

        <div class="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
          <span v-if="changed.length" class="text-[11.5px] text-muted-foreground">
            实际改动：{{ changed.map((c) => FIELD_LABELS[c as keyof BookMetadataFields] ?? c).join('、') }}
          </span>
          <Button
            v-if="hasOverrides && editable"
            size="sm"
            variant="ghost"
            :disabled="restoring"
            class="ml-auto"
            @click="restoreAll"
          >
            ↺ 恢复全部为在线
          </Button>
          <Button
            size="sm"
            variant="primary"
            :disabled="!editable || saving || !dirty"
            :class="hasOverrides ? '' : 'ml-auto'"
            @click="save"
          >
            {{ saving ? '保存中…' : '保存' }}
          </Button>
        </div>
      </Card>
    </template>
  </div>
</template>
