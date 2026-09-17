<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { ACHIEVEMENTS_FIELDS } from '@/data/settingsFields'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

/**
 * YOU → Profile（`/settings/account/profile`）
 *
 * 真实实现：账号展示 + 修改密码 + 退出登录 + **成就开关**。
 * 未支持：头像、显示名、时区、引导重放、已连接账号（OIDC）。
 */

const auth = useAuthStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

onMounted(() => {
  void loadConfig()
})

const oldPin = ref('')
const newPin = ref('')
const pinError = ref('')
const pinOk = ref('')
const pinBusy = ref(false)

async function changePin(): Promise<void> {
  pinError.value = ''
  pinOk.value = ''
  pinBusy.value = true
  try {
    await api.changePin(oldPin.value, newPin.value)
    pinOk.value = '密码已更新'
    oldPin.value = ''
    newPin.value = ''
  } catch (e) {
    pinError.value = e instanceof Error ? e.message : '修改失败'
  } finally {
    pinBusy.value = false
  }
}

function logout(): void {
  auth.logout()
  window.dispatchEvent(new CustomEvent('nf-unauthorized'))
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">个人资料</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Profile</span>
      <span class="text-[11.5px] text-muted-foreground">账号、密码与登录状态</span>
    </div>

    <Card padding="none">
      <div class="flex items-center gap-3 border-b border-border px-4 py-3.5">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground">
          <Icon name="user" class="h-4 w-4" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">{{ auth.user || '已登录' }}</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">单用户轻登录（防局域网他人误入）</div>
        </div>
        <Button size="sm" variant="danger" @click="logout">退出登录</Button>
      </div>

      <div class="px-4 py-3.5">
        <div class="mb-2.5 text-[13px] font-medium text-foreground">修改密码</div>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            v-model="oldPin"
            type="password"
            autocomplete="current-password"
            placeholder="原密码"
            class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
          <input
            v-model="newPin"
            type="password"
            autocomplete="new-password"
            placeholder="新密码（≥4 位）"
            class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          >
          <Button variant="primary" :disabled="pinBusy || !oldPin || !newPin" @click="changePin">保存</Button>
        </div>
        <p v-if="pinError" class="mt-2 text-[11.5px] text-destructive">{{ pinError }}</p>
        <p v-if="pinOk" class="mt-2 text-[11.5px] text-success">{{ pinOk }}</p>
        <p class="mt-2 text-[11px] text-muted-foreground">
          密码保存在 SQLite（首次启动由 AUTH_PIN 初始化；之后以这里修改的为准）。
        </p>
      </div>
    </Card>

    <!-- 成就开关（对应上游 Profile 的 Enable achievements） -->
    <Card padding="none" class="mt-4">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-baseline gap-2">
          <h3 class="text-[13px] font-semibold text-foreground">成就</h3>
          <span class="ml-auto font-mono text-[11px] text-muted-foreground">PREFERENCES</span>
        </div>
        <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          对应上游的 <span class="font-mono">Enable achievements</span>。
          关闭后<strong>不判定、不解锁</strong>，侧栏也不再显示成就入口；
          已解锁的记录不会丢失，重新开启后照常显示。
        </p>
      </div>

      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in ACHIEVEMENTS_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />
      </template>
      <div v-else class="px-4 py-6 text-center text-[12px] text-muted-foreground">加载中…</div>

      <div class="flex items-center justify-end border-t border-border px-4 py-3">
        <Button size="sm" variant="primary" :disabled="saving" @click="saveSection('achievements')">
          保存
        </Button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      label="Profile"
      :groups="['PREFERENCES', 'SECURITY & ACCESS', 'Connected Accounts']"
      :items="[
        '头像上传 / 移除（PNG / JPEG / WEBP，≤5MB）',
        'Full name（显示名）',
        'Username（上游亦不可改，只读展示）',
        'Email（只读，需管理员修改）',
        'Timezone（用于 Early Bird / All-nighter 等时间相关成就）',
        'Guided Tour（重放新手引导）',
        'Connected Accounts（用 OIDC 提供者登录）',
      ]"
      note="本项目为单用户轻登录：有成就有账号展示与改密码，没有头像 / 显示名 / 时区 / OIDC。"
    />
  </div>
</template>
