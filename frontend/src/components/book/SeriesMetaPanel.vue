<script setup lang="ts">
/**
 * 系列简介与系列级字段（第 12 期 C3 SYNOPSIS）。
 *
 * 三条与后端一致的原则，界面必须如实体现：
 *  1. **简介只能来自在线**：抓不到就明说「未找到可信来源」，绝不编造；
 *     抓到时一并展示**来源与置信度**（外部源没有「系列」实体，结果天然带不确定度）。
 *  2. **本地已改过的不会被再次抓取冲掉**：编辑即本地覆盖，标「已本地修改」，
 *     可随时「恢复在线」；覆盖不影响出版社 / 首发年 / 题材（那些取本地聚合的事实）。
 *  3. **两个「册数」不是一个概念**：`owned_count` 是库里实际拥有，
 *     `declared_count` 是外部声明的系列总数。分开显示，不合并成一个数字。
 */
import { computed, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { api, type SeriesMeta } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ name: string; meta: SeriesMeta | null }>()
const emit = defineEmits<{ changed: [] }>()

const ui = useUiStore()
const editing = ref(false)
const draft = ref('')
const saving = ref(false)
const fetching = ref(false)
const expanded = ref(false)

const SOURCE_LABELS: Record<string, string> = {
  openlibrary: 'OpenLibrary',
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
const tagsText = computed(() => (meta.value?.tags ?? []).join(' · '))
const owned = computed(() => meta.value?.owned_count ?? 0)
const declared = computed(() => meta.value?.declared_count ?? 0)

watch(() => props.name, () => {
  editing.value = false
  expanded.value = false
})

function startEdit(): void {
  draft.value = desc.value
  editing.value = true
}

async function save(): Promise<void> {
  saving.value = true
  try {
    await api.saveSeriesMeta(props.name, { description: draft.value })
    editing.value = false
    ui.toast(draft.value.trim() ? '已保存为本地简介' : '已清除本地简介')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

/** 撤销本地覆盖，回退到在线值（与书籍元数据的「恢复在线」同一心智模型） */
async function restore(): Promise<void> {
  saving.value = true
  try {
    await api.saveSeriesMeta(props.name, { description: '' })
    ui.toast('已恢复为在线值')
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
      <h3 class="text-[13px] font-semibold text-foreground">系列简介</h3>
      <Badge v-if="desc && sourceLabel" :tone="overridden ? 'accent' : 'neutral'">
        {{ sourceLabel }}
      </Badge>
      <span v-if="desc && scoreText && !overridden" class="text-[10.5px] text-muted-foreground">
        {{ scoreText }}
      </span>
      <span
        v-if="overridden"
        class="rounded bg-primary/14 px-1.5 py-0.5 text-[10px] text-primary"
      >已本地修改</span>

      <div class="ml-auto flex items-center gap-2">
        <Button v-if="!editing" size="sm" :disabled="fetching" @click="fetchOne">
          {{ fetching ? '抓取中…' : '抓取系列元数据' }}
        </Button>
        <Button v-if="!editing" size="sm" variant="ghost" @click="startEdit">编辑</Button>
        <template v-if="overridden && !editing">
          <button
            type="button"
            :disabled="saving"
            class="cursor-pointer rounded text-[11.5px] text-primary transition-colors hover:text-primary/80 disabled:opacity-50"
            @click="restore"
          >
            ↺ 恢复在线
          </button>
        </template>
      </div>
    </div>

    <!-- 就地编辑：保存后回到展示态，避免“编辑框常驻”把页面撑得很长 -->
    <div v-if="editing" class="mt-2">
      <textarea
        v-model="draft"
        rows="4"
        placeholder="填写系列简介；留空并保存即清除本地简介"
        class="w-full rounded-md border border-border bg-muted px-2.5 py-2 text-[12.5px] leading-relaxed text-foreground outline-none focus:border-ring focus:bg-card"
      />
      <div class="mt-2 flex items-center gap-2">
        <Button size="sm" variant="primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </Button>
        <Button size="sm" variant="ghost" :disabled="saving" @click="editing = false">取消</Button>
        <span class="text-[11px] text-muted-foreground">
          只保存在本应用，不写入书本文件
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
        以免贴一段不相关的简介。可点「抓取系列元数据」再试一次。
      </div>
    </template>

    <!-- 系列级字段：有值才渲染（沿用项目「计数胶囊有值才渲染」的约定，不留占位噪音） -->
    <div
      v-if="meta && (meta.publisher || meta.first_year || tagsText || owned)"
      class="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-muted-foreground"
    >
      <span v-if="meta.publisher">出版社 · {{ meta.publisher }}</span>
      <span v-if="meta.first_year">首发年 · {{ meta.first_year }}</span>
      <span v-if="tagsText" class="truncate">题材 · {{ tagsText }}</span>
      <span>
        册数 · 已有 {{ owned }} 册<span v-if="declared > 0"> / 外部声明共 {{ declared }} 册</span>
      </span>
    </div>
  </div>
</template>
