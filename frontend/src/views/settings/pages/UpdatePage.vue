<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import { UPDATE_FIELDS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { api, type UpdateStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * EXTENSIONS → Updates（`/settings/ext/update`）
 *
 * 第 78 期新增：版本号单一真值源 + 侧栏版本号 / new 提示 + 一键更新。
 * 第 80 期：四个字段全部接通（新增「更新拉取镜像」）；保存后开关 / 间隔**即时生效**，
 * 不再需要重启进程（后端 `server._apply_update_config`）。
 * 口子仍然只有两个：拉取 `update.image` 指的那一个镜像、重建**自身容器** ——
 * 没有「任意容器 / 任意 exec」（见 core/updater.py）。
 *
 * 第 84 期：加**状态卡**（引导式开启）。此前这页只有四个字段 + 一句静态说明，
 * 用户看到「自动更新」开关根本不知道能不能用、为什么没升上去、怎么才能用上：
 * 而默认不挂 docker.sock 意味着 NAS 上默认**用不了**，这个事实必须说清楚，
 * 否则那个开关就是「看着能点、其实不生效」的东西（不做假交互）。
 */

const ui = useUiStore()
const { cfg, files, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

const st = ref<UpdateStatus | null>(null)
const busy = ref('')

/** 自动更新能不能用：开关开 **且** socket 挂着，两个条件缺一不可 */
const autoUsable = computed(() => !!st.value?.auto_apply && !!st.value?.updater_available)

/** 上次自动更新失败（成功过的不算失败，退避计数清零） */
const autoFailed = computed(() => {
  const s = st.value
  if (!s) return false
  return (s.auto_failures ?? 0) > 0 && s.last_auto_result !== 'restarting'
})

/** 时间戳 → 本地可读时间（把裸 epoch 甩给用户是偷懒） */
function fmtTs(ts: number | undefined): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function refresh(): Promise<void> {
  try {
    st.value = await api.updateStatus()
  } catch {
    // 拿不到状态不该让整页空着：字段区与说明卡照常可用
    st.value = null
  }
}

async function run(key: string, label: string, fn: () => Promise<string>): Promise<void> {
  busy.value = key
  try {
    ui.toast(await fn())
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : `${label}失败`)
  } finally {
    busy.value = ''
    await refresh()
  }
}

function checkNow(): Promise<void> {
  return run('check', '检查', async () => {
    await api.updateCheck()
    return '已检查远端版本'
  })
}

function applyNow(): Promise<void> {
  // 不做「点一下就默默重建容器」：重建期间服务会短暂不可用，必须先说清后果
  const ok = window.confirm(
    '立即拉取最新镜像并重建本容器？\n\n' +
      '· 会先自动备份业务数据，备份失败则中止（不会带着数据风险继续更新）；\n' +
      '· 重建期间服务短暂不可用（约十几秒），之后自动恢复。',
  )
  if (!ok) return Promise.resolve()
  return run('apply', '更新', async () => {
    const r = await api.updateApply()
    if (!r.ok) throw new Error(r.message || `更新未完成（${r.stage}）`)
    return r.stage === 'restarting' ? '正在重建容器，稍候自动恢复' : '已提交更新'
  })
}

onMounted(async () => {
  await loadConfig()
  await refresh()
})
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">更新</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Updates</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">版本检查与一键更新</span>
      <Button
        size="sm"
        variant="primary"
        class="ml-auto"
        :disabled="saving"
        @click="saveSection('update')"
      >保存</Button>
    </div>

    <!-- 第 84 期状态卡：自动更新是「开关 + socket」同时成立才可用，
         只摆一个开关而不说「你现在用不了」就是在骗人。 -->
    <Card padding="none" class="mb-4">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">自动更新状态</h3>
        <Badge v-if="st && autoUsable" tone="ok">可用</Badge>
        <Badge v-else-if="st" tone="warn">不可用</Badge>
        <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">
          本地 {{ st?.current ?? '—' }} / 远端 {{ st?.latest ?? '—' }}
        </span>
        <Button size="sm" :disabled="!!busy" @click="refresh">刷新</Button>
        <Button size="sm" :disabled="!!busy" @click="checkNow">
          {{ busy === 'check' ? '检查中…' : '立即检查' }}
        </Button>
        <Button
          size="sm"
          variant="primary"
          :disabled="!!busy || !st?.updater_available"
          @click="applyNow"
        >
          {{ busy === 'apply' ? '处理中…' : '立即更新' }}
        </Button>
      </div>

      <div class="flex flex-col gap-2 px-4 py-3">
        <p class="text-[11.5px] leading-relaxed text-muted-foreground">
          一键更新与自动更新都要求容器挂了
          <code class="font-mono">/var/run/docker.sock</code>。
          <strong v-if="st && !st.updater_available">当前未挂载，下方「自动更新」开关不会生效</strong>
          <span v-else-if="st && !st.auto_apply">自动更新开关当前是关的</span>
          —— 开启步骤：① 在 <code class="font-mono">docker-compose.yml</code> 的
          <code class="font-mono">volumes</code> 下取消注释
          <code class="font-mono">/var/run/docker.sock</code> 那一行；
          ② 打开下方「检查到新版自动更新」并保存本页。
        </p>

        <!-- 失败原因如实显示：第 84 期之前，用户只能对着「有更新」标记猜为什么一直没升上去 -->
        <p
          v-if="autoFailed"
          class="rounded-md bg-danger/10 px-2.5 py-1.5 text-[11.5px] leading-relaxed text-danger"
        >
          自动更新失败{{ st?.auto_failures ? `（已连续 ${st?.auto_failures} 次）` : '' }}：{{ st?.auto_message || '原因未知' }}
          <template v-if="st?.auto_retry_at">
            ，将于 {{ fmtTs(st?.auto_retry_at) }} 自动重试（失败间隔 1 小时 → 6 小时 → 24 小时）。
          </template>
        </p>
        <p v-else-if="st?.auto_apply && st?.updater_available" class="text-[11.5px] text-success">
          自动更新已开启：发现新版本会自动备份数据、拉取镜像并重建本容器。
        </p>

        <p class="text-[11px] leading-relaxed text-muted-foreground">
          每次自动更新前都会自动备份业务数据（PostgreSQL 走 dump、SQLite 整文件拷贝），
          备份落在 <code class="font-mono">config/backups</code>（持久卷，容器重建后仍在），
          保留最近 5 份；<strong>备份失败即中止本次更新</strong>，不会带着数据风险继续。
        </p>
      </div>
    </Card>

    <Card padding="none" class="mb-4">
      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in UPDATE_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <p class="text-[11.5px] text-muted-foreground">
      保存写入 <code class="font-mono">{{ files.settings_file }}</code>（叠加在
      <code class="font-mono">{{ files.config_file }}</code> 之上，不改动其注释）。
    </p>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        版本号来自仓库根 <code class="font-mono">VERSION</code> 文件（单一真值源），侧栏底部与
        <RouterLink to="/whats-new" class="underline">新功能</RouterLink>
        页据此渲染。一键更新须在 <code class="font-mono">docker-compose.yml</code> 的
        <code class="font-mono">volumes</code> 下取消注释
        <code class="font-mono">/var/run/docker.sock</code> 那一行才生效；未挂载时窗口只展示复制升级命令，不做假交互。
      </div>
    </Card>
  </div>
</template>
