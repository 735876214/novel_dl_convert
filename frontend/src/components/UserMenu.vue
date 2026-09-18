<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { useAuthStore } from '@/stores/auth'

/**
 * 顶栏用户浮层（对应上游顶栏头像菜单）。
 *
 * 账号页（/settings/account/profile，含修改密码与退出登录）与登出清 token 逻辑已有，
 * 之前缺的是「顶栏入口」——头像是个静态 div。这里补上点击浮层，
 * 复用 NotificationBell 的「点外部 / Esc 关闭」模式，视觉与顶栏其它浮层一致。
 */
const auth = useAuthStore()
const router = useRouter()

const open = ref(false)
const wrap = ref<HTMLElement | null>(null)

const initial = computed(() => (auth.user || 'U').trim().charAt(0).toUpperCase())

function toggle(): void {
  open.value = !open.value
}

function goProfile(): void {
  open.value = false
  router.push('/settings/account/profile')
}

function logout(): void {
  open.value = false
  auth.logout()
  // 与 ProfilePage 退出一致：清 token 后让外壳弹回登录门禁
  window.dispatchEvent(new CustomEvent('nf-unauthorized'))
}

function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  const t = e.target as Node
  if (wrap.value && !wrap.value.contains(t)) open.value = false
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="wrap" class="relative">
    <button
      type="button"
      :class="[
        'h-8 w-8 shrink-0 cursor-pointer rounded-full border border-border bg-muted shadow-[inset_0_0_0_3px_var(--card)] text-[12px] font-semibold text-foreground transition-colors',
        open ? 'bg-[var(--shell-accent-tint)] text-primary hover:text-primary' : 'hover:bg-muted',
      ]"
      :title="auth.user || '本地用户'"
      :aria-expanded="open"
      aria-label="账户菜单"
      @click.stop="toggle"
    >
      {{ initial }}
    </button>

    <div
      v-if="open"
      class="absolute top-[calc(100%+0.5rem)] right-0 z-50 w-[min(16rem,88vw)] overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-2xl backdrop-blur-md backdrop-saturate-150"
    >
      <div class="flex items-center gap-2.5 border-b border-border px-3.5 py-3">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted text-[13px] font-semibold text-foreground">
          {{ initial }}
        </span>
        <div class="min-w-0">
          <div class="truncate text-[13px] font-medium text-foreground">{{ auth.user || '已登录' }}</div>
          <div class="truncate text-[11px] text-muted-foreground">单用户轻登录</div>
        </div>
      </div>

      <button
        type="button"
        class="flex w-full cursor-pointer items-center gap-2 px-3.5 py-2.5 text-left text-[12.5px] text-foreground transition-colors hover:bg-muted/60"
        @click.stop="goProfile"
      >
        <Icon name="user" class="h-4 w-4 text-muted-foreground" />
        个人资料
      </button>

      <div class="border-t border-border p-2">
        <Button variant="danger" block @click.stop="logout">
          <Icon name="logout" class="mr-1.5 h-4 w-4" />退出登录
        </Button>
      </div>
    </div>
  </div>
</template>
