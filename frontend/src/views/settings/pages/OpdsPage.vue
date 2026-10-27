<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type LibraryEntity, type OpdsCredential } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * DEVICES → OPDS（`/settings/opds`）
 *
 * OPDS（Open Publication Distribution System）是第三方阅读器订阅书库的标准协议：
 * 客户端填一个地址 + 账号密码，就能像逛目录一样浏览、下载。
 *
 * 本项目实现：只读目录 feed（全部 / 最近 / 按作者 / 按系列 / 按标签 / 搜索 / 单书详情 /
 * 封面 / 下载），鉴权用**应用账号**（Basic Auth）。
 *
 * 第 14 期起**按书库暴露**：可见库多于一个时，根 feed 会多一个「按书库」入口，
 * 每个书库有独立地址 `/opds/lib/<库 id>`，可以只订阅其中一个。逐库开关在
 * 「设置 → 书库管理 → 每库设置」的「对 OPDS 暴露」（默认全部暴露）。
 *
 * 第 160 期补上**独立只读账号**：只能读 `/opds/*`，可限定书库范围 —— 给外部阅读器
 * 的 PIN 不再等于交出管理员账号（判据在 `auth.verify_client` / `auth.client_library_scope`）。
 */
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

const libs = ref<LibraryEntity[]>([])

onMounted(async () => {
  await loadConfig()
  try {
    libs.value = (await api.libraries())?.items ?? []
  } catch {
    libs.value = []   // 书库列表取不到不影响本页其它开关，不弹错
  }
  await loadCreds()
})

const enabled = computed(() => Boolean(val('opds.enabled')))
/** 端点是同源根路径（应用挂在 /，前端路由不占用 /opds） */
const origin = computed(() => window.location.origin)
const endpoint = computed(() => `${origin.value}/opds`)
/** 单库地址：库 id 可能含中文 / 空格，URL 里必须编码 */
const libUrl = (id: string) => `${origin.value}/opds/lib/${encodeURIComponent(id)}`

/** 当前账号名：直接从 token 的首段取（格式 user.exp.sig），不必额外请求 */
const account = computed(() => {
  try {
    return (localStorage.getItem('nf_token') || '').split('.')[0] || '（未知）'
  } catch {
    return '（未知）'
  }
})

/** 存**被复制的那条地址**（而不是布尔值）：多行列地址时不会一起变成「已复制」 */
/** 输入框样式（本页新建只读账号表单用） */
const INPUT =
  'h-8 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring'

// ---------------- 只读客户端凭据（第 160 期）----------------
const creds = ref<OpdsCredential[]>([])
const credBusy = ref('')
const newLabel = ref('')
const newUser = ref('')
const newPin = ref('')
/** 新建时勾选的书库；**一个都不勾 = 全部可见库**（与后端空数组语义一致） */
const newLibs = ref<string[]>([])

function libName(id: string): string {
  return libs.value.find((l) => l.id === id)?.name || id
}

function scopeText(c: OpdsCredential): string {
  return c.library_ids.length ? c.library_ids.map(libName).join('、') : '全部可见书库'
}

function fmtUsed(ts: number): string {
  if (!ts) return '从未使用'
  return new Date(ts * 1000).toLocaleString()
}

async function loadCreds(): Promise<void> {
  try {
    creds.value = (await api.opdsCredentials()).items ?? []
  } catch {
    creds.value = []   // 取不到不影响本页开关；新建时后端会给出真实原因
  }
}

async function createCred(): Promise<void> {
  if (credBusy.value || !newUser.value.trim() || !newPin.value) return
  credBusy.value = 'create'
  try {
    await api.createOpdsCredential({
      username: newUser.value.trim(),
      pin: newPin.value,
      label: newLabel.value.trim(),
      library_ids: newLibs.value,
    })
    ui.toast('只读账号已创建')
    newLabel.value = ''
    newUser.value = ''
    newPin.value = ''
    newLibs.value = []
    await loadCreds()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '创建失败')
  } finally {
    credBusy.value = ''
  }
}

async function toggleCred(c: OpdsCredential): Promise<void> {
  credBusy.value = c.id
  try {
    await api.updateOpdsCredential(c.id, { enabled: !c.enabled })
    await loadCreds()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '操作失败')
  } finally {
    credBusy.value = ''
  }
}

async function removeCred(c: OpdsCredential): Promise<void> {
  credBusy.value = c.id
  try {
    await api.deleteOpdsCredential(c.id)
    ui.toast(`已删除账号 ${c.username}`)
    await loadCreds()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  } finally {
    credBusy.value = ''
  }
}

const copied = ref('')
async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = text
    setTimeout(() => (copied.value = ''), 1500)
  } catch {
    ui.toast('复制失败，请手动选中地址')
  }
}

async function toggle(): Promise<void> {
  const before = enabled.value
  setVal('opds.enabled', !before)
  // ⚠️ `saveSection` 失败**不抛**：它只返回 false 并自己弹「保存失败」。
  // 第 135 期前这里不看返回值就追一句「OPDS 已开启」—— toast 是单槽，
  // 失败提示被覆盖成成功；开关也停在新位置，界面与服务端不一致。
  if (!(await saveSection('opds'))) {
    setVal('opds.enabled', before)
    return
  }
  ui.toast(before ? 'OPDS 已关闭' : 'OPDS 已开启')
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">OPDS</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">OPDS</span>
      <span class="text-[11.5px] text-muted-foreground">给第三方阅读器用的目录订阅源</span>
      <span
        v-if="enabled"
        class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] text-emerald-600 dark:text-emerald-400"
      >
        已开启
      </span>
      <span v-else class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">已关闭</span>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">OPDS 目录服务</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            开启后第三方阅读器可用下面的地址订阅书库（关闭时该地址返回 404）
          </div>
        </div>
        <Button size="sm" :variant="enabled ? 'ghost' : 'primary'" :disabled="saving || !cfg" @click="toggle">
          {{ enabled ? '关闭' : '开启' }}
        </Button>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">端点地址</div>
        <div class="flex flex-wrap items-center gap-2">
          <code class="flex-1 truncate rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground">
            {{ endpoint }}
          </code>
          <Button size="sm" @click="copy(endpoint)">{{ copied === endpoint ? '已复制' : '复制' }}</Button>
        </div>
      </div>

      <div v-if="libs.length > 1" class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">按书库订阅</div>
        <div class="mb-2 text-[11.5px] text-muted-foreground">
          每个书库有独立地址，只想订阅其中一个（例如只给孩子设备看漫画库）就填下面对应那条。
          关掉某库的「对 OPDS 暴露」后，它既不出现在这里，直连它的地址也返回 404。
        </div>
        <ul class="space-y-1.5">
          <li v-for="l in libs" :key="l.id" class="flex flex-wrap items-center gap-2">
            <span class="w-24 shrink-0 truncate text-[12.5px] text-foreground">{{ l.name }}</span>
            <code class="min-w-0 flex-1 truncate rounded-md border border-border bg-muted px-2.5 py-1.5 font-mono text-[11.5px] text-foreground">
              {{ libUrl(l.id) }}
            </code>
            <Button size="sm" variant="ghost" @click="copy(libUrl(l.id))">
              {{ copied === libUrl(l.id) ? '已复制' : '复制' }}
            </Button>
          </li>
        </ul>
        <p class="mt-2 text-[11.5px] text-muted-foreground">
          书库导航：<code class="font-mono">{{ origin }}/opds/libraries</code>；
          逐库开关在「设置 → 书库管理 → 每库设置」。
        </p>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">账号</div>
        <div class="text-[12.5px] leading-relaxed text-muted-foreground">
          管理员账号 <code class="font-mono text-foreground">{{ account }}</code> + 登录 PIN
          → 可看<strong>全部可见书库</strong>。第 160 期起还可以建<strong>只读账号</strong>：
          它只能读 OPDS 目录 / 封面 / 下载，且可限定只看某几个库（给孩子的设备、只订阅漫画库）。
        </div>

        <ul v-if="creds.length" class="mt-2.5 space-y-1.5">
          <li
            v-for="c in creds"
            :key="c.id"
            class="flex flex-wrap items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
          >
            <span class="min-w-0 text-[12.5px] text-foreground">
              <b>{{ c.username }}</b>
              <span v-if="c.label" class="ml-1 text-muted-foreground">（{{ c.label }}）</span>
            </span>
            <span class="text-[11.5px] text-muted-foreground">{{ scopeText(c) }}</span>
            <span class="text-[11px] text-muted-foreground/80">{{ fmtUsed(c.last_used_at) }}</span>
            <span
              class="rounded-full px-1.5 py-0.5 text-[10.5px]"
              :class="c.enabled
                ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                : 'bg-muted text-muted-foreground'"
            >
              {{ c.enabled ? '启用' : '停用' }}
            </span>
            <div class="ml-auto flex gap-1">
              <Button size="sm" variant="ghost" :disabled="!!credBusy" @click="toggleCred(c)">
                {{ c.enabled ? '停用' : '启用' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="!!credBusy" @click="removeCred(c)">删除</Button>
            </div>
          </li>
        </ul>
        <p v-else class="mt-2 text-[11.5px] text-muted-foreground">还没有只读账号（管理员账号照常可用）。</p>

        <div class="mt-3 grid gap-2 sm:grid-cols-3">
          <label class="flex flex-col gap-1">
            <span class="text-[11px] text-muted-foreground">备注</span>
            <input v-model="newLabel" type="text" :class="INPUT" placeholder="如 孩子的平板" :disabled="!!credBusy">
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] text-muted-foreground">用户名</span>
            <input v-model="newUser" type="text" :class="INPUT" placeholder="3–32 位" :disabled="!!credBusy">
          </label>
          <label class="flex flex-col gap-1">
            <span class="text-[11px] text-muted-foreground">PIN</span>
            <input v-model="newPin" type="password" :class="INPUT" placeholder="至少 4 位" :disabled="!!credBusy">
          </label>
        </div>
        <div v-if="libs.length" class="mt-2">
          <div class="text-[11.5px] text-muted-foreground">可看的书库（<strong>一个都不勾 = 全部可见书库</strong>）</div>
          <div class="mt-1 flex flex-wrap gap-x-3 gap-y-1">
            <label
              v-for="l in libs"
              :key="l.id"
              class="flex cursor-pointer items-center gap-1.5 text-[12px] text-foreground"
            >
              <input
                v-model="newLibs"
                type="checkbox"
                :value="l.id"
                class="h-3.5 w-3.5 cursor-pointer accent-primary"
                :disabled="!!credBusy"
              >
              {{ l.name }}
            </label>
          </div>
        </div>
        <div class="mt-2 flex justify-end">
          <Button
            size="sm"
            variant="primary"
            :disabled="!!credBusy || !newUser.trim() || !newPin"
            @click="createCred"
          >
            {{ credBusy === 'create' ? '创建中…' : '新建只读账号' }}
          </Button>
        </div>

        <div class="mt-2 text-[11.5px] text-amber-600 dark:text-amber-400">
          注意：Basic 认证是明文传输，请只在可信内网（或套 HTTPS 的反向代理）下开启。
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-2 text-[13px] font-medium text-foreground">客户端怎么填</div>
        <ol class="ml-4 list-decimal space-y-1 text-[12.5px] text-muted-foreground">
          <li>在阅读器里找「添加 OPDS 目录 / 网络书库」这类入口</li>
          <li>地址填上面的端点，用户名 / PIN 填管理员账号，或上面新建的只读账号</li>
          <li>保存后会看到「全部书籍 / 最近添加 / 按作者 / 按系列 / 按标签 / 搜索」</li>
        </ol>
        <p class="mt-2 text-[11.5px] text-muted-foreground">
          已验证的客户端协议：OPDS 1.2（Atom + Dublin Core + OpenSearch）。
          支持 <code class="font-mono">?page=</code> 分页，列表可用
          <code class="font-mono">?sort=recent|title|author|series&amp;order=asc|desc</code> 排序。
        </p>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="OPDS"
      :groups="['SERVER', 'ENDPOINT', 'OPDS ACCOUNTS', 'OPDS NOTES']"
      :items="[
        '每客户端权限细分（只读 / 可下载分区 / 到期时间）——第 160 期只做「只读 + 书库范围」',
        '仅 HTTPS 的强制开关（上游为按部署方式给建议）',
      ]"
      note="本项目已实现：目录开关、端点地址（可复制）、全部/最近/按作者/按系列/按标签/搜索/单书详情/封面/下载、分页与排序参数、Basic 认证（管理员账号或**独立只读账号**，后者可限定书库），以及按书库分别暴露（每个书库有独立地址，可逐库开关）。"
    />
  </div>
</template>
