<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, apiErrorMessage, type TocSourceItem, type TocSourceRow } from '@/lib/api'

/**
 * 「目录来源」区块（第 85 期批次 B）：本地目录不清楚时，从正版官方书城取一份目录来对。
 *
 * 三条界面纪律：
 * 1. **只取目录**：按钮与说明都要写清「只读章节目录，不取正文」——
 *    用户点之前就该知道会发生什么（这是本功能的边界，不是免责声明）；
 * 2. **未验证 / 不可用如实标注**：注册表里 `verified: false` 的显示「未验证」徽标，
 *    `usable: false` 的显示原因且**按钮点不动**（不做假交互）；
 * 3. **失败也要说原因、也要刷新**：后端返回的是原因原文，原样显示；
 *    而且**失败同样落库**，所以 `catch` 里照样 `emit('changed')` ——
 *    父级重取详情才能把「上次为什么没取到」显示出来。
 */
const props = defineProps<{
  bookId: string
  /** 每个来源上次的抓取结果（详情页随详情一起下发） */
  sources?: TocSourceRow[]
  /** 当前生效的书城来源 id；空串 = 用的是本地目录 */
  applied?: string
}>()
const emit = defineEmits<{ changed: [] }>()

const catalog = ref<TocSourceItem[]>([])
const gateReason = ref('')
const busy = ref('')
const manualUrl = ref('')
const message = ref('')
const failed = ref(false)

function rowOf(source: string): TocSourceRow | undefined {
  return (props.sources ?? []).find((s) => s.source === source)
}

/** 上次结果的一句话（`ok=false` 时就是原因原文本身，别再加工） */
function resultText(r: TocSourceRow): string {
  if (!r.ok) return r.note || '上次没取到'
  return `已对齐 ${r.mapped} / ${r.entry_count} 条${r.manual ? '（手动指定书页）' : ''}`
}

onMounted(async () => {
  // 清单很小，且要用来渲染每个来源的可用态 ⇒ 一次性取回比「展开再问」简单且够用。
  // 拿不到就当没有可用来源（静默降级，不阻塞详情页）。
  try {
    const r = await api.tocSources()
    catalog.value = r.items
    gateReason.value = r.enabled ? '' : r.reason
  } catch {
    catalog.value = []
  }
})

async function pick(it: TocSourceItem): Promise<void> {
  busy.value = it.id
  failed.value = false
  message.value = ''
  try {
    const r = await api.tocFetch(props.bookId, it.id, manualUrl.value.trim())
    message.value = `已对齐 ${r.mapped} / ${r.total} 章${r.matched_title ? `（${r.matched_title}）` : ''}`
  } catch (e) {
    failed.value = true
    message.value = apiErrorMessage(e, '取目录失败')
  } finally {
    busy.value = ''
  }
  emit('changed')          // 成功要刷新章节标题；失败也要刷新（原因已经落库）
}

async function restore(): Promise<void> {
  busy.value = '__clear__'
  failed.value = false
  try {
    const r = await api.tocClear(props.bookId)
    message.value = r.cleared ? '已还原为本地目录' : '这本本来就没取过书城目录'
  } catch (e) {
    failed.value = true
    message.value = apiErrorMessage(e, '还原失败')
  } finally {
    busy.value = ''
  }
  emit('changed')
}
</script>

<template>
  <Card padding="none" class="mb-3">
    <div class="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2.5">
      <span class="text-[12.5px] font-semibold text-foreground">目录来源</span>
      <span class="text-[11.5px]" :class="applied ? 'text-foreground' : 'text-muted-foreground'">
        {{ applied ? `当前用书城目录（${applied}）` : '当前用本地目录' }}
      </span>
      <span class="min-w-0 flex-1" />
      <Button
        v-if="applied"
        size="sm"
        variant="ghost"
        :disabled="!!busy"
        @click="restore"
      >
        还原为本地目录
      </Button>
    </div>

    <p class="px-3.5 pt-2 text-[11.5px] text-muted-foreground">
      本地目录看不出章节名时，可以从正版书城取一份目录来对。
      <span class="text-foreground">只读章节目录（标题与顺序），不下载任何正文。</span>
    </p>

    <div class="px-3.5 pt-2">
      <input
        v-model="manualUrl"
        type="text"
        placeholder="书页地址（可选，自动匹配不到时填这里）"
        aria-label="书页地址"
        class="h-8 w-full rounded-md border border-border bg-muted px-2.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
      >
    </div>

    <div
      v-if="gateReason"
      class="mx-3.5 mt-2 rounded-md border border-border bg-muted px-2.5 py-1.5 text-[11.5px] text-muted-foreground"
    >
      {{ gateReason }}
    </div>

    <div
      v-for="it in catalog"
      :key="it.id"
      class="mt-2 flex flex-wrap items-center gap-2 border-t border-border/60 px-3.5 py-2"
    >
      <span class="text-[12.5px] text-foreground">{{ it.label }}</span>
      <span
        v-if="!it.verified"
        class="rounded border border-border px-1.5 py-0.5 text-[10.5px] text-muted-foreground"
        title="该规则未在联网环境里验证过"
      >未验证</span>
      <span
        v-if="!it.usable"
        class="min-w-0 flex-1 text-[11.5px] text-muted-foreground"
      >{{ it.blocked_reason }}</span>
      <span
        v-else-if="rowOf(it.id)"
        class="min-w-0 flex-1 text-[11.5px]"
        :class="rowOf(it.id)!.ok ? 'text-muted-foreground' : 'text-destructive'"
      >{{ resultText(rowOf(it.id)!) }}</span>
      <span v-else class="min-w-0 flex-1" />
      <Button
        size="sm"
        variant="secondary"
        :disabled="!it.usable || !!busy"
        @click="pick(it)"
      >
        {{ busy === it.id ? '取目录中…' : '取目录' }}
      </Button>
    </div>

    <p
      v-if="message"
      class="px-3.5 pt-1 pb-2.5 text-[11.5px]"
      :class="failed ? 'text-destructive' : 'text-muted-foreground'"
    >
      {{ message }}
    </p>
  </Card>
</template>
