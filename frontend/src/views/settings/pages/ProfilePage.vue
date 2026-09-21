<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import GuidedTourModal from '@/components/settings/GuidedTourModal.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { useSettingsDirty } from '@/composables/useSettingsDirty'
import { ACHIEVEMENTS_FIELDS, READING_FIELDS } from '@/data/settingsFields'
import { api } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Profile（`/settings/account/profile`）
 *
 * 真实实现：账号展示 + 修改密码 + 退出登录 + **成就开关** + 头像 + 显示名 + 时区 + 新手引导重放。
 * 未实现（单用户场景无意义）：OIDC 连接、Username（上游亦不可改）、Email（无邮箱体系）。
 */

const auth = useAuthStore()
const ui = useUiStore()
const { cfg, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

// ---------------- 账号资料（第 25 期）----------------
const dName = ref(auth.displayName)
const tz = ref(auth.timezone)
const avatarSrc = ref<string | null>(auth.avatarUrl)
const avatarNonce = ref(Date.now())
const savingProfile = ref(false)
const busyAvatar = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const tourOpen = ref(false)

const dirty = computed(
  () => dName.value !== auth.displayName || tz.value !== auth.timezone,
)

/**
 * 把「资料」页的草稿脏状态上报给设置外壳，让提示条与「放弃更改」也覆盖本页
 * （本页草稿存在页面自己的 ref 里，不在 `useSettingsConfig` 的共享草稿中）。
 * 放弃 = 还原成已保存值，不写服务端。
 */
useSettingsDirty().register({
  key: 'account/profile',
  label: '资料',
  isDirty: () => dirty.value,
  discard: () => {
    dName.value = auth.displayName
    tz.value = auth.timezone
  },
})

// IANA 时区列表：现代浏览器用 Intl 全量，旧环境回落到常用子集。
const TIMEZONES = (() => {
  try {
    const all = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf?.('timeZone')
    if (all && all.length) return all
  } catch {
    /* ignore */
  }
  return [
    'UTC', 'Asia/Shanghai', 'Asia/Tokyo', 'Asia/Kolkata', 'Asia/Hong_Kong',
    'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Europe/Moscow',
    'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
    'Australia/Sydney', 'Pacific/Auckland',
  ]
})()

function syncAvatar(): void {
  avatarSrc.value = auth.avatarUrl ? api.accountAvatarUrl(avatarNonce.value) : null
}

onMounted(() => {
  void loadConfig()
  // 登录后已加载过；此处兜底刷新，保证显示名/时区/头像是最新值
  auth.loadProfile().then(() => {
    dName.value = auth.displayName
    tz.value = auth.timezone
    syncAvatar()
  })
})

async function saveProfile(): Promise<void> {
  if (!dirty.value) return
  savingProfile.value = true
  try {
    const p = await api.updateProfile({ display_name: dName.value, timezone: tz.value })
    auth.applyProfile(p)
    avatarNonce.value = Date.now()
    syncAvatar()
    ui.toast('资料已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    savingProfile.value = false
  }
}

function pickAvatar(): void {
  fileInput.value?.click()
}

async function onAvatar(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // 清空后才能重复选同一文件
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    ui.toast('仅支持 JPG / PNG / WEBP 图片')
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    ui.toast('图片需 ≤ 5MB')
    return
  }
  busyAvatar.value = true
  try {
    const r = await api.uploadAvatar(file)
    auth.avatarUrl = r.avatar_url
    avatarNonce.value = Date.now()
    syncAvatar()
    ui.toast('头像已更新')
  } catch (err) {
    ui.toast(err instanceof Error ? err.message : '上传失败')
  } finally {
    busyAvatar.value = false
  }
}

async function removeAvatar(): Promise<void> {
  if (!window.confirm('移除当前头像？')) return
  busyAvatar.value = true
  try {
    await api.deleteAvatar()
    auth.avatarUrl = null
    avatarSrc.value = null
    ui.toast('已移除头像')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '移除失败')
  } finally {
    busyAvatar.value = false
  }
}

// ---------------- 密码 ----------------
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
      <span class="text-[11.5px] text-muted-foreground">账号、资料与登录状态</span>
      <Button size="sm" variant="danger" class="ml-auto" @click="logout">退出登录</Button>
    </div>

    <!-- 账号资料 -->
    <Card padding="none">
      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <span class="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-full bg-muted text-muted-foreground">
          <img v-if="avatarSrc" :src="avatarSrc" alt="头像" class="h-full w-full object-cover">
          <Icon v-else name="user" class="h-6 w-6" />
        </span>
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">{{ auth.display }}</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">单用户轻登录（防局域网他人误入）</div>
        </div>
        <div class="flex shrink-0 gap-2">
          <Button size="sm" :disabled="busyAvatar" @click="pickAvatar">上传头像</Button>
          <Button v-if="avatarSrc" size="sm" variant="ghost" :disabled="busyAvatar" @click="removeAvatar">移除</Button>
        </div>
        <input
          ref="fileInput"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          class="hidden"
          @change="onAvatar"
        >
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-20 shrink-0 text-[13px] font-medium text-foreground">显示名</div>
        <input
          v-model="dName"
          type="text"
          maxlength="40"
          placeholder="留空则显示账号名"
          class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          @keyup.enter="saveProfile"
        >
      </div>

      <div class="flex items-center gap-4 border-b border-border px-4 py-3.5">
        <div class="w-20 shrink-0 text-[13px] font-medium text-foreground">时区</div>
        <select
          v-model="tz"
          class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
        >
          <option value="">未设置（用服务器本地时）</option>
          <option v-for="z in TIMEZONES" :key="z" :value="z">{{ z }}</option>
        </select>
        <span class="shrink-0 text-[11.5px] text-muted-foreground">影响「晨型人 / 夜猫子」等时间类成就</span>
      </div>

      <div class="flex items-center justify-end gap-2 px-4 py-3">
        <Button size="sm" variant="primary" :disabled="savingProfile || !dirty" @click="saveProfile">
          {{ savingProfile ? '保存中…' : '保存资料' }}
        </Button>
      </div>
    </Card>

    <!-- 密码 -->
    <Card padding="none" class="mt-4">
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

    <!--
      阅读进度口径（第 40 期，对应上游 Kobo 页的 Progress Thresholds）。
      放在成就旁边不是随手摆的：成就的「已读完」判定读的就是这个阈值
      （`core/achievements.py` → `lib_settings.reading_thresholds`），两者是一族。
    -->
    <Card padding="none" class="mt-4">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-baseline gap-2">
          <h3 class="text-[13px] font-semibold text-foreground">阅读进度口径</h3>
          <span class="ml-auto font-mono text-[11px] text-muted-foreground">READING THRESHOLDS</span>
        </div>
        <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          决定「在读 / 已读完」怎么算。统计、书架、成就、Komga 客户端<strong>四处同源</strong> ——
          改这里会同时改变它们的结果，不是只影响某一页。
          每个书库还能在「工具 → 书库管理 → 每库设置」里单独覆写。
        </p>
      </div>

      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in READING_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />
      </template>
      <div v-else class="px-4 py-6 text-center text-[12px] text-muted-foreground">加载中…</div>

      <div class="flex items-center justify-end border-t border-border px-4 py-3">
        <Button size="sm" variant="primary" :disabled="saving" @click="saveSection('reading')">
          保存
        </Button>
      </div>
    </Card>

    <!-- 新手引导（对应上游 Profile 的 Guided Tour 重放） -->
    <Card padding="none" class="mt-4">
      <div class="flex flex-wrap items-center gap-3 px-4 py-3.5">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">新手引导</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            重新观看一次简短的入门引导（书架 / 阅读器 / 设置同步）。离线可用，不影响任何数据。
          </div>
        </div>
        <Button size="sm" @click="tourOpen = true">重放新手引导</Button>
      </div>
    </Card>

    <SettingsUnsupportedCard
      class="mt-4"
      label="Profile"
      :groups="['SECURITY & ACCESS', 'Connected Accounts']"
      :items="[
        'Username（上游亦不可改，只读展示）',
        'Email（本项目无邮箱体系，仅服务端可读）',
        'Connected Accounts（OIDC 单点登录：单用户场景无意义）',
      ]"
      note="本项目为单用户轻登录：已实现账号展示、修改密码、头像上传/移除、显示名、时区（接通时间类成就）、成就开关与新手引导重放；OIDC / Email 在单用户场景无意义，故不提供。"
    />

    <GuidedTourModal v-model:open="tourOpen" />
  </div>
</template>
