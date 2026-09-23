<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type IntegrationService, type IntegrationTestResult } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * DEVICES → Hardcover / Readwise / StoryGraph（三个路由共用这一个组件）
 *
 * 三家的鉴权方式完全不同，且**没有一家用 OAuth**：
 *   · Hardcover：GraphQL + `Bearer <token>`（⚠️ 鉴权失败也可能返 200 + errors）
 *   · Readwise ：REST + `Authorization: Token <token>`（⚠️ 验证成功返 **204** 不是 200）
 *   · StoryGraph：**没有公开 API**，只能存登录态 Cookie，无法自动验证
 *
 * 所以这一页只做两件真实成立的事：**保存凭据** + **能验证的就去真验证**。
 * 「同步任务」（把状态/书评推过去）需要先做书籍匹配，尚未实现 ——
 * 按「不做假交互」的约定，这里不放同步按钮，而是如实标注。
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
        '同步任务（把阅读状态 / 书评 / 书摘推送到对方）——需先做书籍匹配（ISBN / 标题模糊匹配）',
        '从对方拉取书单 / 进度（反向同步）',
        '同步历史与失败重试（本项目现有任务中心可承载，但匹配层未做）',
      ]"
      :note="isStorygraph
        ? '本页已实现：凭据存储（两个 Cookie）。StoryGraph 没有公开 API，上游同样只能用登录态 Cookie 并注明可能失效，因此本项目不提供自动验证与同步。'
        : '本页已实现：凭据存储 + 真实连通性验证（直接请求对方 API 判断 Token 是否有效）。'"
    />
  </div>
</template>
