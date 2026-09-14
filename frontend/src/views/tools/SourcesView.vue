<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type SourceItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** 书源管理：已注册列表 + 批量粘贴 + 文件上传。接真实 /api/sources。 */
const ui = useUiStore()

const sources = ref<SourceItem[]>([])
const loading = ref(true)
const pasteText = ref('')
const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const builtinCount = computed(() => sources.value.filter((s) => s.builtin).length)

function load(): void {
  loading.value = true
  api
    .listSources()
    .then((r) => {
      sources.value = r.sources ?? []
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

onMounted(load)

function submitPaste(): void {
  const text = pasteText.value.trim()
  if (!text) {
    ui.toast('请先粘贴书源 JSON')
    return
  }
  busy.value = true
  api
    .addSourcesText(text)
    .then((r) => {
      ui.toast(`已添加 ${r.added ?? 0} 个书源`)
      pasteText.value = ''
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function onFilePick(e: Event): void {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  api
    .uploadSourcesFile(file)
    .then((r) => {
      ui.toast(`已从文件添加 ${r.added ?? 0} 个书源`)
      load()
    })
    .catch((err: Error) => ui.toast(err.message))
    .finally(() => {
      busy.value = false
      input.value = ''
    })
}

function remove(name: string): void {
  api
    .deleteSource(name)
    .then(() => {
      ui.toast(`已删除 ${name}`)
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
}
</script>

<template>
  <div>
    <PageHead title="书源管理" :desc="`共 ${sources.length} 个书源 · 其中内置 ${builtinCount} 个`" />

    <div class="mb-5 grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">批量粘贴</h3>
        <p class="mb-2.5 text-[11.5px] text-muted-foreground">
          支持 JSON 对象 / 数组 / JSONL 三种格式，一次可导入多个书源。
        </p>
        <textarea
          v-model="pasteText"
          rows="7"
          placeholder='{"name": "示例书源", "search": {"url": "..."}}'
          aria-label="粘贴书源 JSON"
          class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        />
        <div class="mt-2.5 flex items-center gap-2">
          <Button variant="primary" :disabled="busy" @click="submitPaste">导入</Button>
          <Button :disabled="busy" @click="fileInput?.click()">从文件导入</Button>
          <input ref="fileInput" type="file" accept=".json,.jsonl,.txt" class="hidden" @change="onFilePick">
        </div>
      </Card>

      <Card padding="none">
        <div class="flex items-center gap-2 border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">已注册书源</h3>
          <Badge class="ml-auto">{{ sources.length }}</Badge>
        </div>

        <div v-if="loading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

        <div v-else-if="sources.length" class="max-h-[26rem] overflow-y-auto">
          <div
            v-for="s in sources"
            :key="s.name"
            class="flex items-center gap-2.5 border-b border-border/60 px-4 py-2.5 last:border-b-0"
          >
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ s.name }}</span>
            <Badge v-if="s.builtin" tone="accent">内置</Badge>
            <Button
              v-if="!s.builtin"
              size="sm"
              variant="danger"
              title="删除该书源"
              @click="remove(s.name)"
            >
              删除
            </Button>
          </div>
        </div>

        <EmptyState v-else icon="source" title="还没有书源" desc="用左侧的批量粘贴或文件导入添加书源。" />
      </Card>
    </div>
  </div>
</template>
