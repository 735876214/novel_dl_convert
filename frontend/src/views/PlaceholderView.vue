<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'

/**
 * 未知路由兜底页（`/placeholder/:id`）。
 *
 * ⚠️ 这里原本还有张 `VIEW_META`（迁自 v2 的占位视图元信息表，`nav.ts`）。第 32 期删掉：
 * 所有正式视图都已实现，侧栏每个 id 都有真实路由，那张表的 key（`_authors` / `notify` /
 * `sources` …）**一个都到不了**。留着一张不可达的表，只会让人以为还有「未实现的视图」。
 */
const route = useRoute()
const router = useRouter()

const key = computed(() => {
  const param = route.params.id
  if (typeof param === 'string' && param) return param
  const seg = route.path.replace(/^\//, '').split('/')[0]
  return seg || 'dashboard'
})

</script>


<template>
  <div>
    <PageHead :title="key" desc="未知路由" />

    <EmptyState
      icon="alert"
      :title="`${key} 不存在`"
      desc="该页面不存在或链接有误（所有正式视图均已实现，这里仅作未知路由兜底）。"
    >
      <template #action>
        <Button variant="primary" @click="router.push('/')">返回仪表盘</Button>
      </template>
    </EmptyState>
  </div>
</template>
