<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import {
  api,
  type IntegrationService,
  type IntegrationTestResult,
  type SyncPreview,
  type SyncResult,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * DEVICES → Hardcover / Readwise / StoryGraph（三个路由共用这一个组件）
 *
 * 三家的鉴权方式完全不同，且**没有一家用 OAuth**：
 *   · Hardcover：GraphQL + `Bearer <token>`（⚠️ 鉴权失败也可能返 200 + errors）
 *   · Readwise ：REST + `Authorization: Token <token>`（⚠️ 验证成功返 **204** 不是 200）
 *   · StoryGraph：**没有公开 API**，只能存登录态 Cookie（第 52 期起可**启发式**校验）
 *
 * 这一页现在做四件事：**保存凭据** + **验证凭据** + **同步**（预览 / 立即同步 / 可选的自动推送）
 * + **如实标注做不到的**。StoryGraph 不支持同步（没有公开 API），故按 `svc.sync` 不渲染同步卡 ——
 * 不是隐藏一个坏按钮，而是那件事在这里本来就不成立。
 */
const props = defineProps<{ service: string }>()

const ui = useUiStore()
const svc = ref<IntegrationService | null>(null)
const form = ref<Record<string, string>>({})
const loading = ref(true)
const busy = ref(false)
const result = ref<IntegrationTestResult | null>(null)
/** 加载失败信息：失败不能让表单区整个不渲染（会被读成「这家没有可配项」）。 */
const error = ref('')

const isStorygraph = computed(() => props.service === 'storygraph')

// ---- 第 52 期：同步（预览 / 立即同步 / 自动推送）----
const preview = ref<SyncPreview | null>(null)
const syncResult = ref<SyncResult | null>(null)
const syncing = ref(false)
/** 是否已配置凭据：未配置时同步按钮禁用并说明原因（不放「点了没反应」的按钮） */
const hasCreds = computed(() => Object.values(svc.value?.has ?? {}).some(Boolean))

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const all = (await api.integrations()).items
    svc.value = all.find((s) => s.id === props.service) ?? null
    // 回显的是掩码：不动它 = 不修改（后端按此约定处理）
    form.value = { ...(svc.value?.values ?? {}) }
  } catch (e) {
    svc.value = null
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

/**
 * ⚠️ 必须监听 `service`：三页共用这一个组件（靠路由 props 区分），
 * Vue Router 会**复用同一个组件实例** —— 只在 onMounted 里加载的话，
 * 从 Hardcover 切到 Readwise 时 props 变了但数据不会重载，
 * 页面上会停留上一家的内容（实测踩到过：三个路由渲染的都是 Hardcover）。
 */
watch(() => props.service, () => {
  result.value = null
  preview.value = null
  syncResult.value = null
  void load()
})

async function save(): Promise<void> {
  busy.value = true
  result.value = null
  try {
    await api.saveIntegration(props.service, form.value)
    await load()
    ui.toast('已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function test(): Promise<void> {
  busy.value = true
  result.value = null
  try {
    // 带上表单里当前的值：填完直接验证，不必先保存
    result.value = await api.testIntegration(props.service)
  } catch (e) {
    result.value = { ok: false, message: e instanceof Error ? e.message : '验证失败' }
  } finally {
    busy.value = false
  }
}

/** 预览：只算不改、零外呼（Hardcover 的匹配在同步时才做） */
async function runPreview(): Promise<void> {
  preview.value = null
  try {
    preview.value = await api.previewIntegration(props.service)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '预览失败')
  }
}

/** 立即同步（写向对方，不可逆） */
async function runSync(): Promise<void> {
  syncing.value = true
  syncResult.value = null
  try {
    const r = await api.syncIntegration(props.service)
    syncResult.value = r
    ui.toast(r.ok ? `同步完成：${r.pushed} 条` : `同步有 ${r.failed.length} 条失败`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '同步失败')
  } finally {
    syncing.value = false
  }
}

/** 「Enable sync」开关（上游同名）：默认关，打开后写入时旁路自动推送 */
async function toggleAutoPush(): Promise<void> {
  if (!svc.value) return
  const next = !svc.value.auto_push
  try {
    await api.saveIntegration(props.service, { auto_push: next })
    await load()
    ui.toast(next ? '已开启自动推送' : '已关闭自动推送')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ svc?.label || '外部服务' }}</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">{{ svc?.id || service }}</span>
      <span class="text-[11.5px] text-muted-foreground">{{ svc?.desc }}</span>
      <Badge v-if="svc?.verify">可验证</Badge>
      <Badge v-else>无法自动验证</Badge>
    </div>

    <Card padding="none">
      <div v-if="loading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
      <div v-else-if="error" class="flex flex-wrap items-center gap-2 px-4 py-6 text-[12.5px] text-destructive">
        <span>凭据配置加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
      <template v-else-if="svc">
        <div
          v-for="f in svc.fields"
          :key="f.key"
          class="flex flex-wrap items-center gap-3 border-b border-border px-4 py-3.5 last:border-b-0"
        >
          <div class="min-w-[200px] flex-1">
            <div class="text-[12.5px] font-medium text-foreground">{{ f.label }}</div>
            <div v-if="f.hint" class="mt-0.5 text-[11.5px] text-muted-foreground">{{ f.hint }}</div>
          </div>
          <div class="flex items-center gap-2">
            <span v-if="svc.has[f.key]" class="text-[11.5px] text-emerald-600 dark:text-emerald-400">已设置</span>
            <input
              v-model="form[f.key]"
              :type="f.type === 'password' ? 'password' : 'text'"
              class="w-[300px] rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
              :placeholder="svc.has[f.key] ? '•••••••• = 保持不变；清空则删除凭据' : '未设置'"
            />
          </div>
        </div>

        <div class="flex flex-wrap items-center gap-2 px-4 py-3.5">
          <Button size="sm" variant="primary" :disabled="busy" @click="save">保存</Button>
          <Button v-if="svc.verify" size="sm" :disabled="busy" @click="test">
            {{ busy ? '处理中…' : '验证凭据' }}
          </Button>
          <span v-else class="text-[11.5px] text-muted-foreground">
            该服务无公开 API，无法自动验证 —— 保存后凭据即生效
          </span>
          <a
            v-if="svc.doc"
            :href="svc.doc"
            target="_blank"
            rel="noreferrer"
            class="ml-auto text-[11.5px] text-muted-foreground underline"
          >获取凭据的官方说明</a>
        </div>

        <div
          v-if="result"
          class="border-t border-border px-4 py-3 text-[12.5px]"
          :class="result.ok
            ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
            : (result.unsupported ? 'bg-amber-500/10 text-amber-700 dark:text-amber-400' : 'bg-destructive/10 text-destructive')"
        >
          <div>{{ result.message }}</div>
          <div v-if="result.detail" class="mt-1 font-mono text-[11.5px] opacity-80">{{ result.detail }}</div>
        </div>
      </template>
    </Card>

    <Card v-if="svc?.note" class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">{{ svc.note }}</div>
    </Card>

    <!-- 第 52 期：同步。StoryGraph 不支持同步（无公开 API）⇒ 不渲染这张卡 -->
    <Card v-if="svc?.sync" class="mt-4" padding="none">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">同步</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          把本项目的内容推到对方。匹配口径固定为「ISBN 精确 → 规范化书名 + 作者 → 跳过」——
          匹配不上的书会如实列出来，不做模糊强推。
        </p>
      </div>

      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">预览 / 立即同步</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            {{ preview
              ? `待推送 ${preview.total} ${preview.unit}（涉及 ${preview.books} 本）` +
                (preview.remote_match_at_sync ? '；与对方条目的匹配在同步时才进行' : '')
              : '预览只统计本地待推内容，不向对方发请求' }}
          </div>
        </div>
        <Button size="sm" :disabled="syncing" @click="runPreview">预览</Button>
        <Button size="sm" variant="primary" :disabled="syncing || !hasCreds" @click="runSync">
          {{ syncing ? '同步中…' : '立即同步' }}
        </Button>
      </div>
      <p v-if="!hasCreds" class="border-b border-border px-4 pb-3 text-[11.5px] text-muted-foreground">
        还没配置凭据 —— 先在上面填好并保存，同步按钮才会可用。
      </p>

      <div class="flex flex-wrap items-center gap-3 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">Enable sync（自动推送）</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            打开后，新增批注 / 修改阅读状态 / 保存评分书评时会自动推给
            {{ svc?.label }}；默认关闭，推送失败只记录，不影响你刚做的操作
          </div>
        </div>
        <button
          type="button"
          role="switch"
          :aria-checked="Boolean(svc?.auto_push)"
          class="relative h-[18px] w-8 shrink-0 cursor-pointer rounded-full transition-colors"
          :class="svc?.auto_push ? 'bg-primary' : 'bg-muted'"
          @click="toggleAutoPush"
        >
          <span
            class="absolute top-[2px] h-[14px] w-[14px] rounded-full bg-card transition-transform duration-200"
            :class="svc?.auto_push ? 'translate-x-[16px]' : 'translate-x-[2px]'"
          />
        </button>
      </div>

      <!-- 同步结果：成功 / 跳过（含原因）/ 失败（含原因） -->
      <div v-if="syncResult" class="border-t border-border px-4 py-3 text-[12.5px]">
        <div
          :class="syncResult.ok
            ? 'text-emerald-700 dark:text-emerald-400'
            : 'text-amber-700 dark:text-amber-400'"
        >
          成功 {{ syncResult.pushed }} · 跳过 {{ syncResult.skipped.length }} ·
          失败 {{ syncResult.failed.length }}
        </div>
        <ul
          v-if="syncResult.skipped.length"
          class="mt-1.5 ml-4 list-disc space-y-0.5 text-[11.5px] text-muted-foreground"
        >
          <li v-for="s in syncResult.skipped.slice(0, 8)" :key="s.book_id">
            {{ s.title || s.book_id }} —— {{ s.reason }}
          </li>
        </ul>
        <ul
          v-if="syncResult.failed.length"
          class="mt-1.5 ml-4 list-disc space-y-0.5 text-[11.5px] text-destructive"
        >
          <li v-for="f in syncResult.failed.slice(0, 8)" :key="f.book_id">
            {{ f.title || f.book_id }} —— {{ f.error }}
          </li>
        </ul>
        <p class="mt-1.5 text-[11.5px] text-muted-foreground">
          每次同步都会在「任务中心」留一条记录（含失败原因），可回看。
        </p>
      </div>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        <div class="mb-1.5 font-medium text-foreground">凭据存在哪里</div>
        存在服务端的设置覆盖层（<code class="font-mono">settings.json</code>），与其它配置一起随
        <code class="font-mono">CONFIG_DIR</code> 备份。页面上<strong>只回显掩码</strong>：
        显示 <code class="font-mono">••••••••</code> 时原样提交即保持不变，<strong>把它删空再保存就是删除凭据</strong>。
        三家服务都<strong>不是 OAuth</strong>，所以没有回调地址、也没有授权跳转——把 Token / Cookie 粘进来即可。
      </div>
    </Card>

    <SettingsUnsupportedCard
      :label="svc?.label || '外部服务'"
      :groups="['SYNC', 'MATCHING']"
      :items="[
        '从对方拉取书单 / 进度（反向同步）—— 本项目只做「推」，不拉',
        '人工匹配确认页（逐本挑选对方条目）—— 匹配口径固定为「ISBN → 规范化书名 + 作者 → 跳过」，不做人工确认',
        'StoryGraph 的同步 —— 它没有公开 API，向对方站点的非官方写入会因改版随时失效，故只提供 Cookie 校验',
      ]"
      :note="isStorygraph
        ? '本页已实现：凭据存储（两个 Cookie）+ 启发式有效性校验（带 Cookie 请求站点，被引导到登录页即判失效；网络异常单独归类为连接失败，不算成 Cookie 无效）。不做同步 —— 没有公开 API。'
        : '本页已实现：凭据存储 + 真实连通性验证（直接请求对方 API 判断 Token 是否有效）+ 同步（预览 / 立即同步 / 可选的自动推送），同步结果含成功 / 跳过 / 失败计数与逐条原因，并在任务中心留痕。'"
    />
  </div>
</template>
