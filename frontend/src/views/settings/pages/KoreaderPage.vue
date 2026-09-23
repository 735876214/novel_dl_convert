<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type KoreaderDoc, type KoreaderStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * DEVICES → KOReader（`/settings/koreader`）
 *
 * KOReader 的「同步服务器」（kosync）协议很小，本页把它接到本项目的阅读进度上：
 * 在 KOReader 上读到哪，回到这里也能看到；反之亦然。
 *
 * 三个必须对齐的协议细节（实现见 `core/koreader.py`）：
 *   1. 鉴权头是 `x-auth-user` / `x-auth-key`，其中 key = **密码的 MD5**（不是 Basic）；
 *   2. 文档标识是 **partialMD5**（12 个采样点），不是整文件 MD5；
 *   3. `percentage` 是 0–1；`progress` 对 EPUB 是 XPointer、对 PDF/漫画是页码。
 */
const ui = useUiStore()

const st = ref<KoreaderStatus | null>(null)
const docs = ref<KoreaderDoc[]>([])
const loading = ref(true)
const busy = ref(false)
/** 加载失败信息：失败时头部原会渲染成「已关闭」（假象），须显式报错。 */
const error = ref('')

const username = ref('')
const password = ref('')

const endpoint = computed(() => `${window.location.origin}/koreader`)
const copied = ref(false)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    st.value = await api.koreaderStatus()
    username.value = st.value.username
    docs.value = (await api.koreaderDocs()).items
  } catch (e) {
    st.value = null
    docs.value = []
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function save(): Promise<void> {
  busy.value = true
  try {
    await api.saveKoreader({
      enabled: st.value?.enabled ?? false,
      username: username.value,
      password: password.value,
    })
    password.value = ''
    await load()
    ui.toast('已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function toggle(): Promise<void> {
  if (!st.value) return
  st.value.enabled = !st.value.enabled
  await save()
  ui.toast(st.value.enabled ? '已开启进度互通' : '已关闭')
}

async function scan(): Promise<void> {
  busy.value = true
  try {
    const r = await api.koreaderScan()
    await load()
    ui.toast(`已为 ${r.scanned} 本书建立文档索引`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '扫描失败')
  } finally {
    busy.value = false
  }
}

async function copyEndpoint(): Promise<void> {
  try {
    await navigator.clipboard.writeText(endpoint.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    ui.toast('复制失败，请手动选中地址')
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">KOReader</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">KOReader</span>
      <span class="text-[11.5px] text-muted-foreground">与 KOReader 设备互通阅读进度</span>
      <span
        v-if="st?.enabled"
        class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
      >
        已开启
      </span>
      <span v-else class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">已关闭</span>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">加载中…</Card>

    <!-- 加载失败：可重试的错误态（不与「已关闭」混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>KOReader 状态加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

    <Card v-else padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">进度同步服务</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启后 KOReader 可用下面的地址推送 / 拉取阅读进度（关闭时返回 404）
          </div>
        </div>
        <Button size="sm" :variant="st?.enabled ? 'ghost' : 'primary'" :disabled="busy || !st" @click="toggle">
          {{ st?.enabled ? '关闭' : '开启' }}
        </Button>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">同步地址</div>
        <div class="flex flex-wrap items-center gap-2">
          <code class="flex-1 truncate rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground">
            {{ endpoint }}
          </code>
          <Button size="sm" @click="copyEndpoint">{{ copied ? '已复制' : '复制' }}</Button>
        </div>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">账号</div>
        <div class="grid gap-3 md:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-[12px] text-muted-foreground">用户名</span>
            <input
              v-model="username"
              type="text"
              class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-[12px] text-muted-foreground">
              密码<span class="ml-1">（{{ st?.has_key ? '留空 = 不修改' : '首次必须设置' }}）</span>
            </span>
            <input
              v-model="password"
              type="password"
              class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            />
          </label>
        </div>
        <div class="mt-2 flex items-center gap-2">
          <Button size="sm" variant="primary" :disabled="busy" @click="save">保存</Button>
          <span v-if="st?.has_key" class="text-[11.5px] text-muted-foreground">已设置同步密钥（存的是密码的 MD5）</span>
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-1.5 flex flex-wrap items-center gap-2 text-[13px] font-medium text-foreground">
          <span>文档索引</span>
          <Badge tone="accent">已索引 {{ st?.doc_count ?? 0 }} / {{ st?.book_count ?? 0 }}</Badge>
        </div>
        <div class="mb-2.5 text-[11.5px] text-muted-foreground">
          KOReader 用 <b>partialMD5</b>（只采样 12 个点，不是整文件 MD5）标识文档，本项目用文件名派生的 id，
          两边需要一张对照表。改动书库后请重新扫描。
        </div>
        <Button size="sm" :disabled="busy" @click="scan">{{ busy ? '处理中…' : '扫描书库' }}</Button>

        <div v-if="docs.length" class="mt-3 max-h-[280px] overflow-auto rounded-md border border-border">
          <table class="w-full text-[11.5px]">
            <thead class="sticky top-0 bg-card text-left text-muted-foreground">
              <tr>
                <th class="px-3 py-2">书名</th>
                <th class="px-3 py-2">文件名</th>
                <th class="px-3 py-2">文档标识（partialMD5）</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in docs" :key="d.book_id" class="border-t border-border/60">
                <td class="px-3 py-1.5 text-foreground">{{ d.title }}</td>
                <td class="px-3 py-1.5 font-mono text-muted-foreground">{{ d.name }}</td>
                <td class="px-3 py-1.5 font-mono text-muted-foreground">{{ d.doc_md5 }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        <div class="mb-1.5 font-medium text-foreground">KOReader 里怎么填</div>
        <ol class="ml-4 list-decimal space-y-1">
          <li>打开「工具 → 进度同步（Progress sync）」</li>
          <li>自定义同步服务器填上面的地址（<code class="font-mono">{{ endpoint }}</code>）</li>
          <li>用户名 / 密码填本页设置的这对（KOReader 会把密码做 MD5 后作为密钥发送）</li>
        </ol>
        <p class="mt-2">
          进度映射：EPUB 用 XPointer 里的 <code class="font-mono">DocFragment[N]</code> 对应本项目的章节序号；
          PDF / 漫画用页码。<b>反向写入时 XPointer 只定位到章首</b>（我们只知道读到第几章，不知道章内位置），
          准确位置由 <code class="font-mono">percentage</code> 兜底，KOReader 不会因此跳错。
        </p>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="KOReader"
      :groups="['SYNC', 'DEVICES']"
      :items="[
        '多设备管理（查看 / 撤销某台设备的同步状态）',
        '服务端注册流程（users/create 仅为兼容客户端保留，账号仍由本页设定）',
        '注解 / 书签（kosync 协议只同步阅读进度）',
      ]"
      note="已实现：kosync 协议四个端点（healthcheck / users/auth / users/create / syncs/progress 的 GET+PUT），文档索引（partialMD5 + md5(basename) 双口径），进度双向映射（章节序号 ↔ XPointer/DocFragment，PDF 与漫画用页码）。"
    />
  </div>
</template>
