<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { VIEW_META } from '@/data/nav'

const route = useRoute()
const router = useRouter()

const key = computed(() => {
  const param = route.params.id
  if (typeof param === 'string' && param) return param
  const seg = route.path.replace(/^\//, '').split('/')[0]
  return seg || 'dashboard'
})

const meta = computed(
  () => VIEW_META[key.value] ?? { icon: 'alert', title: key.value, desc: '该视图尚未实现' },
)
</script>

<template>
  <div>
    <PageHead :title="meta.title" :desc="meta.desc" />

    <EmptyState
      :icon="meta.icon"
      :title="`${meta.title} 不存在`"
      desc="该页面不存在或链接有误（所有正式视图均已实现，这里仅作未知路由兜底）。"
    >
      <template #action>
        <Button variant="primary" @click="router.push('/')">返回仪表盘</Button>
      </template>
    </EmptyState>
  </div>
</template>
