<script setup lang="ts">
/**
 * 系列级元数据（第 12 期 C3 SYNOPSIS，第 57 期补全四字段编辑）。
 *
 * 四条与后端一致的原则，界面必须如实体现：
 *  1. **简介只能来自在线**：抓不到就明说「未找到可信来源」，绝不编造；
 *     抓到时一并展示**来源与置信度**（外部源没有「系列」实体，结果天然带不确定度）。
 *  2. **四个字段都能本地覆盖**（简介 / 出版社 / 首发年 / 题材），改过的不会被再次抓取冲掉；
 *     每个字段可单独「恢复在线」—— **空串 = 撤销该字段的覆盖**（后端 `set_local` 语义），
 *     所以「恢复在线」只提交该字段本身，其它字段的覆盖不受影响。
 *  3. **两个「册数」不是一个概念**：`owned_count` 是库里实际拥有，
 *     `declared_count` 是外部声明的系列总数。分开显示，不合并成一个数字。
 *  4. 出版社 / 首发年 / 题材在没有本地覆盖时来自**成员书聚合**（零猜测的本地事实），
 *     界面标出来源，不含糊其辞。
 */
import { computed, reactive, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { api, type SeriesMeta, type SeriesMetaState } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{
  name: string
  meta: SeriesMeta | null
  /** 逐字段明细（`/api/series/{name}` 的 `meta_state`）：用来标「本地覆盖 / 聚合来源」 */
  state?: SeriesMetaState | null
}>()
const emit = defineEmits<{ changed: [] }>()

const ui = useUiStore()
const editing = ref(false)
const saving = ref(false)
const fetching = ref(false)
const expanded = ref(false)

type Field = 'description' | 'publisher' | 'first_year' | 'tags'
/** 字段区三兄弟的中文名（简介单列一块，标签写在模板里） */
const FIELD_LABELS: Record<Exclude<Field, 'description'>, string> = {
  publisher: '出版社',
  first_year: '首发年',
  tags: '题材',
}
const SCALAR_FIELDS: Exclude<Field, 'description'>[] = ['publisher', 'first_year', 'tags']

const SOURCE_LABELS: Record<string, string> = {
  openlibrary: 'Open Library',
  googlebooks: 'Google Books',
}

const meta = computed(() => props.meta)
const desc = computed(() => (meta.value?.description ?? '').trim())
const overridden = computed(() => meta.value?.overridden?.description === true)
/** 在线来源标签：本地编辑优先，其次在线来源名（没有就不显示徽标） */
const sourceLabel = computed(() => {
  if (overridden.value) return '本地编辑'
  const src = meta.value?.source ?? ''
  return SOURCE_LABELS[src] ?? src
})
/** 置信度：外部源没有系列实体，靠成员书打分挑候选 —— 如实展示分数，不粉饰 */
const scoreText = computed(() => {
  const s = meta.value?.score ?? 0
  return s > 0 ? `置信度 ${Math.round(s * 100)}%` : ''
})
const tagsText = computed(() => (meta.value?.tags ?? []).join('、'))
const owned = computed(() => meta.value?.owned_count ?? 0)
const declared = computed(() => meta.value?.declared_count ?? 0)

/** 某字段是否被本地覆盖 */
function isOverridden(f: Field): boolean {
  return meta.value?.overridden?.[f] === true
}
/** 某字段的当前值（字符串形态，供模板展示与草稿初始化） */
function fieldText(f: Field): string {
  const v = f === 'tags' ? tagsText.value : (meta.value?.[f] ?? '')
  return String(v || '').trim()
}
/** 该字段当前生效值来自哪里（有本地覆盖时不显示来源，避免自相矛盾） */
function fieldOrigin(f: Field): string {
  const st = props.state?.[f]
  if (!st || isOverridden(f)) return ''
  if (Array.isArray(st.aggregated) ? st.aggregated.length : String(st.aggregated || '').trim()) {
    return '成员书聚合'
  }
  return st.online ? '在线' : ''
}

const draft = reactive({ description: '', publisher: '', first_year: '', tags: '' })

watch(() => props.name, () => {
  editing.value = false
  expanded.value = false
})

function startEdit(): void {
  draft.description = desc.value
  draft.publisher = fieldText('publisher')
  draft.first_year = fieldText('first_year')
  draft.tags = (meta.value?.tags ?? []).join('、')
  editing.value = true
}

/** 首发年只收 4 位年份或空（空 = 清除覆盖）；写坏值不如不写 */
function yearError(): string {
  const v = draft.first_year.trim()
  if (!v) return ''
  return /^(1[5-9]\d{2}|20\d{2})$/.test(v) ? '' : '首发年请填 4 位年份（如 1951），留空表示清除'
}

async function save(): Promise<void> {
  const bad = yearError()
  if (bad) {
    ui.toast(bad)
    return
  }
  saving.value = true
  try {
    // 四个字段一起提交：**空串 = 撤销该字段的本地覆盖**（后端语义，界面文案已写明）
    await api.saveSeriesMeta(props.name, {
      description: draft.description,
      publisher: draft.publisher,
      first_year: draft.first_year.trim(),
      tags: draft.tags,
    })
    editing.value = false
    ui.toast('已保存为本地系列元数据')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

/** 单字段「恢复在线」：只提交该字段空串 —— 别的字段的本地覆盖不受影响 */
async function restoreField(f: Field): Promise<void> {
  saving.value = true
  try {
    await api.saveSeriesMeta(props.name, { [f]: '' })
    ui.toast(`已恢复「${f === 'description' ? '系列简介' : FIELD_LABELS[f]}」为在线 / 聚合值`)
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复失败')
  } finally {
    saving.value = false
  }
}

async function fetchOne(): Promise<void> {
  fetching.value = true
  try {
    const res = await api.fetchSeriesMeta(props.name)
    // 未命中不是错误：如实告诉用户「没找到可信来源」，不伪造成成功
    ui.toast(res.ok ? `已抓取（${res.result.matched_title || '在线候选'}）` : res.result.error || '未找到')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '抓取失败')
  } finally {
    fetching.value = false
  }
}
</script>

<template>
  <div class="rounded-[var(--shell-radius)] border border-border bg-card px-4 py-3">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="text-[13px] font-semibold text-foreground">系列元数据</h3>
      <Badge v-if="desc && sourceLabel" :tone="overridden ? 'accent' : 'neutral'">
        {{ sourceLabel }}
      </Badge>
      <span v-if="desc && scoreText && !overridden" class="text-[10.5px] text-muted-foreground">
        {{ scoreText }}
      </span>
      <span
        v-if="overridden"
        class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
      >简介已本地修改</span>

      <div class="ml-auto flex items-center gap-2">
        <Button v-if="!editing" size="sm" :disabled="fetching" @click="fetchOne">
          {{ fetching ? '抓取中…' : '抓取系列元数据' }}
        </Button>
        <Button v-if="!editing" size="sm" variant="ghost" @click="startEdit">编辑</Button>
        <!-- 简介的「恢复在线」：只提交 description 空串，不动另外三个字段的覆盖 -->
        <button
          v-if="overridden && !editing"
          type="button"
          :disabled="saving"
          class="cursor-pointer rounded text-[11.5px] text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
          @click="restoreField('description')"
        >
          ↺ 恢复在线
        </button>
      </div>
    </div>

    <!-- 就地编辑：四个字段一次改完；空值 = 清除该字段的本地覆盖 -->
    <div v-if="editing" class="mt-2">
      <label class="mb-1 block text-[11px] text-muted-foreground">系列简介</label>
      <textarea
        v-model="draft.description"
        rows="4"
        placeholder="填写系列简介；留空并保存即清除本地简介"
        class="w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
      />
      <div class="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div>
          <label class="mb-1 block text-[11px] text-muted-foreground">出版社</label>
          <input
            v-model="draft.publisher"
            class="w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            placeholder="留空 = 清除本地覆盖"
          >
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-muted-foreground">首发年</label>
          <input
            v-model="draft.first_year"
            class="w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            placeholder="如 1951；留空 = 清除"
          >
        </div>
        <div>
          <label class="mb-1 block text-[11px] text-muted-foreground">题材（用、或,分隔）</label>
          <input
            v-model="draft.tags"
            class="w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            placeholder="科幻、太空歌剧"
          >
        </div>
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </Button>
        <Button size="sm" variant="ghost" :disabled="saving" @click="editing = false">取消</Button>
        <span class="text-[11px] text-muted-foreground">
          只保存在本应用，不写入书本文件；留空并保存 = 清除该字段的本地覆盖
        </span>
      </div>
    </div>

    <template v-else>
      <p
        v-if="desc"
        class="mt-2 text-[12.5px] leading-relaxed text-muted-foreground"
        :class="!expanded ? 'line-clamp-3' : ''"
      >
        {{ desc }}
      </p>
      <button
        v-if="desc && desc.length > 120"
        type="button"
        class="mt-1 cursor-pointer text-[11px] text-primary transition-colors hover:text-primary/80"
        @click="expanded = !expanded"
      >
        {{ expanded ? '收起' : '展开' }}
      </button>

      <!-- 空态：如实说明「为什么没有」，而不是留一句占位文案 -->
      <div
        v-else
        class="mt-2 rounded-md border border-dashed border-border px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground"
      >
        未找到可信的在线系列简介 —— 外部元数据源没有「系列」这个实体，
        只能在用系列名检索到的结果里挑与成员书对得上的那一条；对不上就不给，
        以免贴一段不相关的简介。可点「抓取系列元数据」再试一次，或直接「编辑」自己写。
      </div>
    </template>

    <!--
      系列级字段：出版社 / 首发年 / 题材（各自可单独恢复到在线 / 聚合值）+ 册数。
      有值才渲染，沿用项目「计数胶囊有值才渲染」的约定，不留占位噪音。
    -->
    <div
      v-if="meta"
      class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11.5px] text-muted-foreground"
    >
      <span v-for="f in SCALAR_FIELDS" :key="f" class="flex items-center gap-1.5">
        <template v-if="fieldText(f)">
          <span>{{ FIELD_LABELS[f] }} · {{ fieldText(f) }}</span>
          <span v-if="isOverridden(f)" class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary">
            本地
          </span>
          <button
            v-if="isOverridden(f)"
            type="button"
            :disabled="saving"
            class="cursor-pointer text-[10.5px] text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
            @click="restoreField(f)"
          >
            ↺ 恢复
          </button>
          <span v-else-if="fieldOrigin(f)" class="text-[10.5px] opacity-70">{{ fieldOrigin(f) }}</span>
        </template>
        <!-- 没值时也给「恢复」口子：否则覆盖成空后再也回不到在线值 -->
        <template v-else-if="isOverridden(f)">
          <span>{{ FIELD_LABELS[f] }} · （空）</span>
          <button
            type="button"
            :disabled="saving"
            class="cursor-pointer text-[10.5px] text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
            @click="restoreField(f)"
          >
            ↺ 恢复在线
          </button>
        </template>
      </span>
      <span v-if="owned || declared">
        册数 · 已有 {{ owned }} 册<span v-if="declared > 0"> / 外部声明共 {{ declared }} 册</span>
      </span>
    </div>
  </div>
</template>
