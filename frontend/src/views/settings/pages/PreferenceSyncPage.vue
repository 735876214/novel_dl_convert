<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { usePrefSyncStore } from '@/stores/prefSync'
import { useUiStore } from '@/stores/ui'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'

/**
 * YOU → Reader → General（`/settings/reader/general`）：偏好与同步。
 *
 * 两层概念（用户拍板）：
 *   · **模式** = 具名的整套偏好快照（eBook 排版含 13 档主题与字体 / PDF / 漫画 /
 *     应用主题·点缀色·圆角 / 书封样式），可被任意设备「应用」；
 *   · **设备** = 各自持有配置。应用模式 = **拷贝**内容，之后各改各的 ——
 *     不会因为别人改了模式本体而被动跟着变。
 *
 * 两类「改」的落盘方式不同，这也是本页两个按钮存在的原因：
 *   · 设备配置的改动**即时生效并自动同步**（无需手动保存）；
 *   · 模式**本体**只在你点「保存到当前模式 / 另存为新模式」时才写 → 不会静默影响别人。
 */
const sync = usePrefSyncStore()
const ui = useUiStore()

onMounted(() => {
  // init 幂等（boot 有 booted 守卫）；从别的入口进来时这里兜底
  sync.init()
})

/** 内联编辑：kind = profile / device 的哪个字段在编辑 */
const editing = ref<{ kind: 'profile' | 'device' | 'new'; id: string | number } | null>(null)
const draft = ref('')

function startEdit(kind: 'profile' | 'device' | 'new', id: string | number, value: string): void {
  editing.value = { kind, id }
  draft.value = value
}

function cancelEdit(): void {
  editing.value = null
  draft.value = ''
}

async function confirmEdit(): Promise<void> {
  const e = editing.value
  const name = draft.value.trim()
  if (!e || !name) return
  try {
    if (e.kind === 'new') await sync.saveAsNewProfile(name)
    else if (e.kind === 'profile') await sync.renameProfile(Number(e.id), name)
    else await sync.renameDevice(String(e.id), name)
    ui.toast('已保存')
    cancelEdit()
  } catch (err) {
    ui.toast(err instanceof Error ? err.message : '保存失败')
  }
}

async function applyProfile(id: number, name: string): Promise<void> {
  if (!window.confirm(`把「${name}」应用到本设备？会覆盖本设备当前的偏好（本机缓存与外观都会更新）。`)) return
  try {
    await sync.applyProfile(id)
    ui.toast(`已应用「${name}」`)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '应用失败')
  }
}

async function saveToCurrent(): Promise<void> {
  const prof = sync.activeProfile
  if (!prof) return
  if (!window.confirm(`用本设备当前配置覆盖模式「${prof.name}」？\n已应用该模式的其它设备不受影响（它们是各自的副本）。`)) return
  try {
    await sync.saveToCurrentProfile()
    ui.toast('已保存到当前模式')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  }
}

async function removeProfile(id: number, name: string): Promise<void> {
  if (!window.confirm(`删除模式「${name}」？\n模式本身会消失，但**已应用它的设备配置不受影响**（只解除来源标记）。`)) return
  try {
    const detached = await sync.removeProfile(id)
    ui.toast(detached ? `已删除，${detached} 台设备解除引用` : '已删除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

async function removeDevice(id: string, name: string): Promise<void> {
  if (!window.confirm(`移除设备「${name}」？它的配置记录会从服务端删掉；那台设备下次打开时会用本机配置重新登记。`)) return
  try {
    await sync.removeDevice(id)
    ui.toast('已移除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '移除失败')
  }
}

function fmtTime(ts: number): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** 相对时间，用来一眼看出哪台设备最近在用 */
function fmtAgo(ts: number): string {
  if (!ts) return '—'
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 90) return '刚刚'
  if (s < 3600) return `${Math.round(s / 60)} 分钟前`
  if (s < 86400) return `${Math.round(s / 3600)} 小时前`
  return `${Math.round(s / 86400)} 天前`
}

const profileName = (pid: number | null): string => {
  if (!pid) return '未套用'
  return sync.profiles.find((p) => p.id === pid)?.name ?? `#${pid}（已删除）`
}

const isThisDevice = (id: string): boolean => id === sync.deviceId
const sortedDevices = computed(() =>
  [...sync.devices].sort((a, b) => (isThisDevice(b.id) ? 1 : 0) - (isThisDevice(a.id) ? 1 : 0) || b.last_seen - a.last_seen),
)
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">偏好与同步</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">General</span>
      <span class="text-[11.5px] text-muted-foreground">
        阅读与外观偏好可存成「模式」，供不同设备套用；每台设备也可以各用各的
      </span>
      <span
        v-if="sync.offline"
        class="ml-auto rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-600 dark:text-amber-400"
      >
        离线 · 未同步
      </span>
    </div>

    <!-- 当前设备 -->
    <Card class="mb-3">
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-[13px] font-semibold text-foreground">本设备</span>
        <template v-if="editing?.kind === 'device' && editing.id === sync.deviceId">
          <input
            v-model="draft"
            type="text"
            class="h-7 w-44 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            @keyup.enter="confirmEdit"
            @keyup.esc="cancelEdit"
          >
          <Button size="sm" @click="confirmEdit">保存</Button>
          <Button size="sm" variant="ghost" @click="cancelEdit">取消</Button>
        </template>
        <template v-else>
          <span class="text-[12.5px] text-foreground">{{ sync.deviceName }}</span>
          <button
            type="button"
            class="cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="startEdit('device', sync.deviceId, sync.deviceName)"
          >
            改名
          </button>
        </template>
        <span class="ml-auto text-[11.5px] text-muted-foreground">
          最后同步：{{ sync.device ? fmtAgo(sync.device.last_seen) : '尚未同步' }}
        </span>
      </div>

      <div class="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <span class="text-[12.5px] text-muted-foreground">当前模式</span>
        <span class="text-[12.5px] font-medium text-foreground">{{ profileName(sync.device?.active_profile_id ?? null) }}</span>
        <span
          v-if="sync.dirty"
          class="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-600 dark:text-amber-400"
        >
          已修改（与模式不一致）
        </span>

        <span class="ml-auto flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            :disabled="!sync.activeProfile || !sync.dirty || sync.busy"
            @click="saveToCurrent"
          >
            保存到当前模式
          </Button>
          <Button size="sm" :disabled="sync.busy" @click="startEdit('new', 0, '')">另存为新模式…</Button>
        </span>
      </div>

      <div v-if="editing?.kind === 'new'" class="mt-2 flex flex-wrap items-center gap-2">
        <input
          v-model="draft"
          type="text"
          placeholder="新模式名称，如「iPad 夜间」"
          class="h-7 w-56 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring"
          @keyup.enter="confirmEdit"
          @keyup.esc="cancelEdit"
        >
        <Button size="sm" @click="confirmEdit">创建</Button>
        <Button size="sm" variant="ghost" @click="cancelEdit">取消</Button>
      </div>

      <p class="mt-2 text-[11.5px] text-muted-foreground">
        本设备的改动**即时生效并自动同步**；模式本体只在你点上面两个按钮时才写入 ——
        所以你的调整不会静默影响其它设备。
      </p>
    </Card>

    <!-- 模式列表 -->
    <Card class="mb-3" padding="none">
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <span class="text-[13px] font-semibold text-foreground">
          模式 <span class="tabular-nums text-muted-foreground">{{ sync.profiles.length }}</span>
        </span>
        <span class="text-[11.5px] text-muted-foreground">应用 = 拷贝到本设备，之后各改各的</span>
      </div>

      <p v-if="!sync.profiles.length" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        还没有模式。把当前这套调参「另存为新模式」，其它设备就能一键套用。
      </p>

      <div
        v-for="p in sync.profiles"
        :key="p.id"
        class="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <template v-if="editing?.kind === 'profile' && editing.id === p.id">
          <input
            v-model="draft"
            type="text"
            class="h-7 w-44 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            @keyup.enter="confirmEdit"
            @keyup.esc="cancelEdit"
          >
          <Button size="sm" @click="confirmEdit">保存</Button>
          <Button size="sm" variant="ghost" @click="cancelEdit">取消</Button>
        </template>
        <template v-else>
          <span class="text-[12.5px] font-medium text-foreground">{{ p.name }}</span>
          <span
            v-if="sync.device?.active_profile_id === p.id"
            class="rounded-full bg-primary/10 px-2 py-0.5 text-[11px] text-primary"
          >
            本设备正在用
          </span>
          <span class="ml-auto text-[11.5px] text-muted-foreground">更新于 {{ fmtTime(p.updated_at) }}</span>
          <Button size="sm" :disabled="sync.busy" @click="applyProfile(p.id, p.name)">应用到本设备</Button>
          <button
            type="button"
            class="cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="startEdit('profile', p.id, p.name)"
          >
            重命名
          </button>
          <button
            type="button"
            class="cursor-pointer text-[11.5px] text-muted-foreground hover:text-destructive"
            @click="removeProfile(p.id, p.name)"
          >
            删除
          </button>
        </template>
      </div>
    </Card>

    <!-- 设备列表 -->
    <Card padding="none">
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <span class="text-[13px] font-semibold text-foreground">
          我的设备 <span class="tabular-nums text-muted-foreground">{{ sync.devices.length }}</span>
        </span>
        <Button size="sm" variant="ghost" :disabled="sync.busy" @click="sync.retry()">立即同步</Button>
      </div>

      <p v-if="!sync.devices.length" class="px-4 py-6 text-center text-[12.5px] text-muted-foreground">
        还没有登记的设备。
      </p>

      <div
        v-for="d in sortedDevices"
        :key="d.id"
        class="flex flex-wrap items-center gap-2 border-b border-border/60 px-4 py-2.5 last:border-b-0"
      >
        <template v-if="editing?.kind === 'device' && editing.id === d.id">
          <input
            v-model="draft"
            type="text"
            class="h-7 w-44 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            @keyup.enter="confirmEdit"
            @keyup.esc="cancelEdit"
          >
          <Button size="sm" @click="confirmEdit">保存</Button>
          <Button size="sm" variant="ghost" @click="cancelEdit">取消</Button>
        </template>
        <template v-else>
          <span class="text-[12.5px] text-foreground">{{ d.name || '未命名设备' }}</span>
          <span v-if="isThisDevice(d.id)" class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">本机</span>
          <span class="rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground">
            {{ profileName(d.active_profile_id) }}
          </span>
          <span class="ml-auto text-[11.5px] text-muted-foreground">{{ fmtAgo(d.last_seen) }}</span>
          <button
            type="button"
            class="cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="startEdit('device', d.id, d.name)"
          >
            改名
          </button>
          <button
            type="button"
            class="cursor-pointer text-[11.5px] text-muted-foreground hover:text-destructive"
            @click="removeDevice(d.id, d.name || d.id)"
          >
            移除
          </button>
        </template>
      </div>

      <p class="border-t border-border/60 px-4 py-2.5 text-[11.5px] text-muted-foreground">
        说明：本项目没有实时推送通道，**其它设备的改动要等这台设备下次打开（或点「立即同步」）才可见**。
        离线时照常可改可用，恢复后自动推送。
      </p>
    </Card>

    <SettingsUnsupportedCard
      label="Preference Sync"
      :groups="['WHERE TO SAVE READER PREFERENCES', 'WHERE TO SAVE APPEARANCE PREFERENCES']"
      :items="[
        '跨设备实时推送（需长连接；本项目为「下次打开/手动同步」）',
        '冲突逐字段自动合并（本项目为整包覆盖：设备配置或模式快照二选一）',
        '按偏好分类单独选择保存位置（本项目是阅读+外观整套一起同步）',
      ]"
      note="本项目已实现：模式（整套偏好快照）的新建/应用/重命名/删除、每台设备各自的配置、设备列表（改名/移除/查看当前模式）、改动即时落盘与自动同步、离线降级与恢复后重推、外观与阅读偏好一并同步。"
    />
  </div>
</template>
