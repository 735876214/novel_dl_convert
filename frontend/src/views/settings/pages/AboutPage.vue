<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Card from '@/components/ui/Card.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'

/**
 * EXTENSIONS → About（`/settings/ext/about`）
 *
 * 上游把「关于」放在 Help 菜单（Documentation / What's New / About BookOrbit），
 * 本项目保留为设置页的一页。
 */

const { files, loadConfig } = useSettingsConfig()

onMounted(() => loadConfig())
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">关于</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">About</span>
      <Badge tone="accent">本项目扩展</Badge>
    </div>

    <Card>
      <dl class="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
        <div
          v-for="item in [
            { k: '应用', v: 'NovelForge · 书籍轨道' },
            { k: '定位', v: 'TXT → EPUB 转换 + 在线阅读平台' },
            { k: '前端', v: 'Vue 3 + Pinia + Tailwind v4' },
            { k: '后端', v: 'FastAPI + SQLite' },
            { k: '鉴权', v: '单用户轻登录（Bearer Token）' },
            { k: '设置存储', v: files.settings_file || 'CONFIG_DIR/settings.json' },
          ]"
          :key="item.k"
          class="min-w-0"
        >
          <dt class="text-[11px] text-muted-foreground">{{ item.k }}</dt>
          <dd class="mt-0.5 truncate text-[12.5px] text-foreground">{{ item.v }}</dd>
        </div>
      </dl>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        设置页分区结构对齐上游 BookOrbit（6 分组 / 38 页）。迁移对照基准见
        <code class="font-mono text-foreground">docs/bookorbit-settings-inventory.md</code>；
        原始采集证据见
        <code class="font-mono text-foreground">docs/review/bookorbit-settings-capture.md</code>。
      </div>
      <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted-foreground">
        <span>对应上游 Help 菜单：</span>
        <RouterLink to="/docs" class="underline hover:text-primary">Documentation</RouterLink>
        <RouterLink to="/whats-new" class="underline hover:text-primary">What's New</RouterLink>
        <RouterLink to="/settings/ext/advanced" class="underline hover:text-primary">高级</RouterLink>
      </div>
    </Card>
  </div>
</template>
