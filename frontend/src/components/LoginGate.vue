<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import { useAuthStore } from '@/stores/auth'

const emit = defineEmits<{ authed: [] }>()

const auth = useAuthStore()
const user = ref('admin')
const pin = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(user.value.trim(), pin.value)
    emit('authed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-[var(--background)] p-4">
    <div class="w-full max-w-sm rounded-lg border border-border bg-card p-8 shadow-lg">
      <div class="mb-6 text-center">
        <div
          class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-2xl text-primary-foreground"
        >
          📚
        </div>
        <h1 class="text-lg font-semibold text-foreground">NovelForge</h1>
        <p class="mt-1 text-sm text-muted-foreground">输入账号密码以进入书库</p>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <label class="block">
          <span class="mb-1 block text-xs text-muted-foreground">账号</span>
          <input
            v-model="user"
            type="text"
            autocomplete="username"
            class="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground outline-none focus:border-ring"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-muted-foreground">密码 / PIN</span>
          <input
            v-model="pin"
            type="password"
            autocomplete="current-password"
            class="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground outline-none focus:border-ring"
            @keyup.enter="submit"
          />
        </label>

        <p v-if="error" class="text-xs text-destructive">{{ error }}</p>

        <Button variant="primary" block :disabled="loading" class="w-full" @click="submit">
          {{ loading ? '登录中…' : '进入' }}
        </Button>
      </form>

      <p class="mt-4 text-center text-[11px] text-muted-foreground">
        默认账号 admin / 密码 changeme，请通过环境变量 AUTH_USER / AUTH_PIN / AUTH_SECRET 修改。
      </p>
    </div>
  </div>
</template>
