<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
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
 * 未支持：独立的 OPDS 账号体系（上游可为不同客户端建不同账号与权限）。
 */
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

onMounted(() => loadConfig())

const enabled = computed(() => Boolean(val('opds.enabled')))
/** 端点是同源根路径（应用挂在 /，#/x 是 hash 路由，不影响 /opds） */
const endpoint = computed(() => `${window.location.origin}/opds`)

/** 当前账号名：直接从 token 的首段取（格式 user.exp.sig），不必额外请求 */
const account = computed(() => {
  try {
    return (localStorage.getItem('nf_token') || '').split('.')[0] || '（未知）'
  } catch {
    return '（未知）'
  }
})

const copied = ref(false)
async function copyEndpoint(): Promise<void> {
  try {
    await navigator.clipboard.writeText(endpoint.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    ui.toast('复制失败，请手动选中地址')
  }
}

async function toggle(): Promise<void> {
  setVal('opds.enabled', !enabled.value)
  await saveSection('opds')
  ui.toast(enabled.value ? 'OPDS 已开启' : 'OPDS 已关闭')
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
          <Button size="sm" @click="copyEndpoint">{{ copied ? '已复制' : '复制' }}</Button>
        </div>
      </div>

      <div class="border-b border-border px-4 py-3.5">
        <div class="mb-1.5 text-[13px] font-medium text-foreground">账号</div>
        <div class="text-[12.5px] text-muted-foreground">
          用户名 <code class="font-mono text-foreground">{{ account }}</code>，密码 = 你的登录 PIN。
          OPDS 客户端用 HTTP Basic 认证，只认这套应用账号（不另建一套凭据）。
        </div>
        <div class="mt-1.5 text-[11.5px] text-amber-600 dark:text-amber-400">
          注意：Basic 认证是明文传输，请只在可信内网（或套 HTTPS 的反向代理）下开启。
        </div>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-2 text-[13px] font-medium text-foreground">客户端怎么填</div>
        <ol class="ml-4 list-decimal space-y-1 text-[12.5px] text-muted-foreground">
          <li>在阅读器里找「添加 OPDS 目录 / 网络书库」这类入口</li>
          <li>地址填上面的端点，用户名填 <code class="font-mono">{{ account }}</code>，密码填 PIN</li>
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
        'OPDS 账号管理（独立账号 / 每客户端权限 / 失效时间）——本项目用应用账号',
        '仅 HTTPS 的强制开关（上游为按部署方式给建议）',
        '按书库分别暴露 feed（本项目单一 OUTPUT_DIR）',
      ]"
      note="本项目已实现：目录开关、端点地址（可复制）、全部/最近/按作者/按系列/按标签/搜索/单书详情/封面/下载、分页与排序参数、Basic 认证（账号=应用账号）。"
    />
  </div>
</template>
