<script setup lang="ts">
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
</script>

<template>
  <div
    id="toast"
    role="status"
    aria-live="polite"
    class="pointer-events-none fixed bottom-6 left-1/2 z-60 max-w-[80vw] rounded-md border border-border bg-card px-3.5 py-2 text-[12.5px] text-foreground shadow-lg transition-all duration-200"
    :class="ui.toastMessage ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0'"
    style="transform: translateX(-50%)"
  >
    {{ ui.toastMessage }}
  </div>
</template>
