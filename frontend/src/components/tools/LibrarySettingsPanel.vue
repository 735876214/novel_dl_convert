<script setup lang="ts">
/**
 * 逐库设置面板（第 13 期）：「投递 / 元数据 / 命名」按**库**分开设。
 *
 * 语义只有一条 —— **生效值 = 每库覆写 ?? 全局值**。所以每一项都同时给出
 * 「全局值」与「是否已覆盖」：用户才能判断这个库到底跟不跟全局走。这也是
 * 「恢复继承」按钮存在的理由（恢复后全局再改，它会自动跟着变）。
 *
 * 每项改完**立即落库**（工具页的习惯是即时生效），不做「草稿 + 保存」——
 * 少一份可能与服务端不同步的前端状态。失败就重新拉一次，绝不留假状态。
 *
 * `schema` 由后端按库类型能力裁过（漫画库不会出现元数据策略），前端不重复判断。
 */
import { computed, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import { api, type LibrarySettingItem, type LibrarySettingsResult } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ libraryId: string }>()
const emit = defineEmits<{ (e: 'changed'): void }>()
const ui = useUiStore()

const data = ref<LibrarySettingsResult | null>(null)
const loading = ref(false)
const busy = ref('')
/** 文本类（`str`）的未提交草稿：边打边存太吵，改成回车 / 失焦时提交 */
const drafts = ref<Record<string, string>>({})

const POLICY_LABELS: Record<string, string> = {
  overwrite: '覆盖',
  fill_only: '只填空',
  skip: '跳过',
}

async function load(): Promise<void> {
  if (!props.libraryId) {
    data.value = null
    return
  }
  loading.value = true
  try {
    data.value = await api.librarySettings(props.libraryId)
    drafts.value = {}
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取每库设置失败')
    data.value = null
  } finally {
    loading.value = false
  }
}

watch(() => props.libraryId, () => void load(), { immediate: true })

const items = computed<LibrarySettingItem[]>(() => data.value?.schema ?? [])
const rawOverrides = computed<Record<string, unknown>>(() => data.value?.overrides ?? {})

/** 逐字段策略表的字段清单：直接取全局值的键，界面不另写一份字段表 */
const policyFields = computed<string[]>(() => {
  const g = data.value?.global?.['metadata_fetch.fields']
  return g && typeof g === 'object' ? Object.keys(g as Record<string, string>) : []
})

function isOverridden(key: string): boolean {
  return data.value?.overridden?.[key] === true
}

function valueOf(key: string): unknown {
  return data.value?.values?.[key]
}

/** 全局值的可读文本：布尔显示开 / 关，免得界面上出现裸 `true` */
function globalText(key: string): string {
  const g = data.value?.global?.[key]
  if (typeof g === 'boolean') return g ? '开' : '关'
  if (g === null || g === undefined || g === '') return '—'
  return String(g)
}

/** 某字段的策略：本库覆写优先；空串 = 该字段继承全局 */
function policyOf(key: string, field: string): string {
  const raw = (rawOverrides.value[key] as Record<string, string>) || {}
  return raw[field] ?? ''
}

function draftOf(key: string): string {
  return drafts.value[key] ?? String(valueOf(key) ?? '')
}

async function save(values: Record<string, unknown>, tag: string): Promise<void> {
  if (!props.libraryId) return
  busy.value = tag
  try {
    data.value = await api.librarySettingsUpdate(props.libraryId, values)
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
    await load()
  } finally {
    busy.value = ''
  }
}

async function reset(keys?: string[]): Promise<void> {
  if (!props.libraryId) return
  busy.value = keys?.length ? `reset:${keys[0]}` : 'reset'
  try {
    data.value = await api.librarySettingsReset(props.libraryId, keys)
    ui.toast(keys?.length ? `已恢复继承：${keys[0]}` : '已全部恢复继承全局')
    emit('changed')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '恢复继承失败')
  } finally {
    busy.value = ''
  }
}

function commitText(key: string): void {
  const next = draftOf(key).trim()
  const cur = String(valueOf(key) ?? '')
  if (!next) {
    ui.toast('不能留空；要跟回全局请点「恢复继承」')
    drafts.value[key] = cur
    return
  }
  if (next === cur) return
  delete drafts.value[key]
  void save({ [key]: next }, `set:${key}`)
}
</script>

<template>
  <div v-if="loading && !data" class="px-4 py-6 text-[12.5px] text-muted-foreground">读取中…</div>
  <div v-else-if="!data" class="px-4 py-6 text-[12.5px] text-muted-foreground">
    点书库行上的「设置」，在这里逐库调策略
  </div>
  <template v-else>
    <div class="border-b border-border px-4 py-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-medium text-foreground">「{{ data.name }}」每库设置</span>
        <Badge>{{ data.library_type }}</Badge>
        <Button size="sm" variant="ghost" class="ml-auto" :disabled="!!busy" @click="reset()">
          全部恢复继承
        </Button>
      </div>
      <div class="mt-0.5 text-[11.5px] leading-relaxed text-muted-foreground">
        没设过的项**继承全局**（全局改了就跟着变）；标「已覆盖」的是这个库单独设过的。
      </div>
    </div>

    <div
      v-for="it in items"
      :key="it.key"
      class="flex flex-wrap items-start gap-3 border-b border-border px-4 py-3 last:border-b-0"
    >
      <div class="min-w-[12rem] flex-1">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-[12.5px] text-foreground">{{ it.label }}</span>
          <Badge :tone="isOverridden(it.key) ? 'accent' : undefined">
            {{ isOverridden(it.key) ? '已覆盖' : '继承全局' }}
          </Badge>
          <code class="text-[11px] text-muted-foreground">{{ it.key }}</code>
        </div>
        <div class="mt-0.5 text-[11px] leading-relaxed text-muted-foreground">
          {{ it.note }}
          <span v-if="isOverridden(it.key)" class="ml-1">
            （全局：{{ globalText(it.key) }}）
          </span>
        </div>
      </div>

      <div class="flex shrink-0 flex-wrap items-center gap-2">
        <template v-if="it.kind === 'bool'">
          <Button
            v-for="v in [true, false]"
            :key="String(v)"
            size="sm"
            :variant="valueOf(it.key) === v ? 'primary' : 'ghost'"
            :disabled="busy === `set:${it.key}`"
            @click="save({ [it.key]: v }, `set:${it.key}`)"
          >
            {{ v ? '开' : '关' }}
          </Button>
        </template>

        <template v-else-if="it.kind === 'enum'">
          <Button
            v-for="o in it.options"
            :key="o"
            size="sm"
            :variant="valueOf(it.key) === o ? 'primary' : 'ghost'"
            :disabled="busy === `set:${it.key}`"
            @click="save({ [it.key]: o }, `set:${it.key}`)"
          >
            {{ o }}
          </Button>
        </template>

        <template v-else-if="it.kind === 'number'">
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            :value="valueOf(it.key)"
            class="w-36 accent-primary"
            @change="save({ [it.key]: Number(($event.target as HTMLInputElement).value) }, `set:${it.key}`)"
          />
          <code class="text-[12px] text-foreground">{{ valueOf(it.key) }}</code>
        </template>

        <template v-else-if="it.kind === 'policy_map'">
          <label
            v-for="f in policyFields"
            :key="f"
            class="flex items-center gap-1 text-[11.5px] text-muted-foreground"
          >
            {{ f }}
            <select
              class="rounded-md border border-border bg-transparent px-1.5 py-1 text-[11.5px] text-foreground outline-none focus:border-primary"
              :value="policyOf(it.key, f)"
              @change="save({ [it.key]: { [f]: ($event.target as HTMLSelectElement).value || null } }, `set:${it.key}`)"
            >
              <option value="">继承</option>
              <option v-for="(label, p) in POLICY_LABELS" :key="p" :value="p">
                {{ label }}
              </option>
            </select>
          </label>
        </template>

        <template v-else>
          <input
            class="w-56 rounded-md border border-border bg-transparent px-2.5 py-1.5 text-[12.5px] text-foreground outline-none focus:border-primary"
            :value="draftOf(it.key)"
            @input="drafts[it.key] = ($event.target as HTMLInputElement).value"
            @keyup.enter="commitText(it.key)"
            @blur="commitText(it.key)"
          />
        </template>

        <Button
          v-if="isOverridden(it.key)"
          size="sm"
          variant="ghost"
          :disabled="!!busy"
          @click="reset([it.key])"
        >
          恢复继承
        </Button>
      </div>
    </div>

    <div v-if="!items.length" class="px-4 py-6 text-[12.5px] text-muted-foreground">
      这个库类型没有可覆写的项
    </div>
  </template>
</template>
