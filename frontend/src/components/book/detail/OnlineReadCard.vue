<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, apiErrorMessage, type OnlineStatus, type SourceStatus } from '@/lib/api'

/**
 * 「在线阅读」区块（第 93 期）：把**用户自己的书源**接到阅读器上。
 *
 * 与紧挨着它的「目录来源」（`TocSourceCard`，第 85 期）共用同一套匹配
 * （`toc_sources.best_match`），但目的是两件事：那边只取一份目录来对标题，
 * 这边绑的是**一个书页地址**，绑完就逐章读正文。
 *
 * 四条界面纪律：
 * 1. **不做假交互**：源列表里不能逐章读的那个（`online_support` 非空）**如实标注并禁用**，
 *    原因照抄后端给的原文。理由见 `store.sources_status` 的 docstring ——
 *    判据只有一处，否则「界面能选、选完点进去 400」。
 * 2. **绑定要落服务端**（`online_bind` 表）：换了客户端也认，这正是「跨客户端续读」的前提。
 * 3. **本地能读也照样显示这块**：本地阅读仍是默认动作（详情页那个主按钮不动），
 *    这里只是**多给一条**路 —— 源站有更新时用户可能就想到这儿读。
 * 4. **解绑零文件触碰**：只删登记。缓存留着，重绑同一页立刻又能离线读。
 */
const props = defineProps<{
  bookId: string
  /** 详情页可把已取到的状态传进来省一次请求；不传就自己取。 */
  status?: OnlineStatus
}>()
const emit = defineEmits<{ changed: [] }>()

const router = useRouter()
const st = ref<OnlineStatus | null>(props.status ?? null)
const sources = ref<SourceStatus[]>([])
const manualUrl = ref('')
const busy = ref('')
const message = ref('')
const failed = ref(false)

/** 能从源站页面看出是哪一页（给用户一个可核对的凭据，不显示完整 URL 太长） */
const hostOf = computed(() => {
  const u = st.value?.url ?? ''
  try {
    return u ? new URL(u).host : ''
  } catch {
    return ''
  }
})

function usable(it: SourceStatus): boolean {
  return it.usable && !it.online_support
}

/** 这个源为什么不能用来在线读（空串 = 能）—— 闸门 / 逐章支持，两句都照原文说 */
function blockReason(it: SourceStatus): string {
  return it.blocked_reason || it.online_support
}

async function refresh(): Promise<void> {
  try {
    const r = await api.onlineStatus(props.bookId)
    st.value = r
  } catch {
    /* 拿不到状态就不显示已绑定的那条（这块会退化成「只列可绑的来源」） */
  }
}

onMounted(async () => {
  if (!props.status) await refresh()
  // 清单很小，且要用来渲染每个源能不能用 ⇒ 一次性取回比「展开再问」简单且够用。
  try {
    const r = await api.sourcesStatus()
    sources.value = r.items
  } catch {
    sources.value = []
  }
})

async function bind(it: SourceStatus): Promise<void> {
  busy.value = it.name
  failed.value = false
  message.value = ''
  try {
    const r = await api.onlineBind(props.bookId, {
      source: it.name,
      url: manualUrl.value.trim() || undefined,
    })
    message.value = r.manual
      ? `已绑定到手动指定的书页（${r.title || r.url}）`
      : `已绑定《${r.title}》（置信度 ${r.confidence.toFixed(2)}）`
    manualUrl.value = ''
  } catch (e) {
    failed.value = true
    message.value = apiErrorMessage(e, '绑定书源失败')
  } finally {
    busy.value = ''
  }
  await refresh()
  // 绑完就把状态交回给详情页：那块横幅之外，详情页头部也能据此显示「在线读」入口
  emit('changed')
}

async function unbind(): Promise<void> {
  busy.value = '__unbind__'
  failed.value = false
  message.value = ''
  try {
    await api.onlineUnbind(props.bookId)
    message.value = '已解绑（在线缓存留着，重绑同一页立刻又能离线读）'
  } catch (e) {
    failed.value = true
    message.value = apiErrorMessage(e, '解绑失败')
  } finally {
    busy.value = ''
  }
  await refresh()
  emit('changed')
}

async function startOnline(): Promise<void> {
  await router.push(`/online/${props.bookId}`)
}
</script>

<template>
  <Card padding="none" class="mb-3">
    <div class="flex flex-wrap items-center gap-2 border-b border-border px-3.5 py-2.5">
      <Icon name="globe" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
      <span class="text-[12.5px] font-semibold text-foreground">在线阅读</span>
      <span class="text-[11.5px]" :class="st?.bound ? 'text-foreground' : 'text-muted-foreground'">
        <template v-if="st?.bound">
          已绑定 {{ st.display_name || st.source }}
          <template v-if="hostOf">（{{ hostOf }}）</template>
          · 读到这里第 {{ (st.pos || 0) + 1 }} 章 · 本机已缓存 {{ st.cache.cached }} 章
        </template>
        <template v-else>还没有绑定书源</template>
      </span>
      <span class="min-w-0 flex-1" />
      <Button v-if="st?.bound" size="sm" variant="ghost" :disabled="!!busy" @click="unbind">
        解绑
      </Button>
      <Button v-if="st?.bound && st.available" size="sm" variant="primary" @click="startOnline">
        开始在线读
      </Button>
    </div>

    <p class="px-3.5 pt-2 text-[11.5px] text-muted-foreground">
      用你自己的书源逐章读正文。内容来自源站，正文以纯文本呈现（源站样式与脚本都不会带进来）；
      读过的章节会缓存在本机，断网时还能接着读，阅读位置记在服务端 —— 换客户端从同一处续读。
    </p>

    <!-- 已绑定但不可用：如实说清原因（闸门没开 / 这个源不能逐章读），不给一个点不动的按钮 -->
    <div
      v-if="st?.bound && !st.available"
      class="mx-3.5 mt-2 rounded-md border border-border bg-muted px-2.5 py-1.5 text-[11.5px] text-muted-foreground"
    >
      {{ st.reason || '当前不可用' }}
    </div>

    <div class="px-3.5 pt-2">
      <input
        v-model="manualUrl"
        type="text"
        placeholder="书页地址（可选：自动匹配不到、或想读另一版本时填这里）"
        aria-label="书页地址"
        class="h-8 w-full rounded-md border border-border bg-muted px-2.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
      >
    </div>

    <div
      v-for="it in sources"
      :key="it.name"
      class="mt-2 flex flex-wrap items-center gap-2 border-t border-border/60 px-3.5 py-2"
    >
      <span class="text-[12.5px] text-foreground">{{ it.display_name || it.name }}</span>
      <span
        v-if="blockReason(it)"
        class="min-w-0 flex-1 text-[11.5px] text-muted-foreground"
      >{{ blockReason(it) }}</span>
      <span v-else class="min-w-0 flex-1 text-[11.5px] text-muted-foreground">
        可逐章在线阅读
      </span>
      <Button
        size="sm"
        variant="secondary"
        :disabled="!usable(it) || !!busy"
        @click="bind(it)"
      >
        {{ busy === it.name ? '绑定中…' : (st?.bound ? '改绑到这个源' : '绑定并开始') }}
      </Button>
    </div>

    <p
      v-if="!sources.length"
      class="px-3.5 pt-2 pb-1 text-[11.5px] text-muted-foreground"
    >
      还没有可用的书源 —— 到「设置 → 书源」导入或添加一个再来。
    </p>

    <p
      v-if="message"
      class="px-3.5 pt-1 pb-2.5 text-[11.5px]"
      :class="failed ? 'text-destructive' : 'text-muted-foreground'"
    >
      {{ message }}
    </p>
  </Card>
</template>
