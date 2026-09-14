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
      :title="`${meta.title} 将在后续实现`"
      desc="本轮先交付外壳与仪表盘，其余视图照同一套组件铺开即可。"
    >
      <template #action>
        <Button variant="primary" @click="router.push('/')">返回仪表盘</Button>
      </template>
    </EmptyState>
  </div>
</template>
