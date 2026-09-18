<script setup lang="ts">
import { RouterLink } from 'vue-router'

import PageHead from '@/components/ui/PageHead.vue'
import Card from '@/components/ui/Card.vue'

/** Documentation：帮助总览（对应上游 Help → Documentation）。链接指向应用内真实路由。 */
const sections = [
  {
    title: '开始使用',
    desc: '把 TXT 投进去，自动转成 EPUB 并在线阅读。',
    links: [
      { to: '/', label: '仪表盘' },
      { to: '/shelf', label: '书架' },
      { to: '/settings/admin/book-dock', label: '收书目录' },
    ],
  },
  {
    title: '阅读',
    desc: 'EPUB / PDF / 漫画阅读器，支持偏好与多端同步。',
    links: [
      { to: '/settings/appearance/theme', label: '外观与阅读偏好' },
      { to: '/settings/reader/ebook', label: '阅读器设置' },
      { to: '/settings/reader/general', label: '偏好与同步' },
    ],
  },
  {
    title: '整理与发现',
    desc: '智能书架、系列、作者、批注与统计。',
    links: [
      { to: '/smart-scopes', label: '智能书架' },
      { to: '/series', label: '系列' },
      { to: '/authors', label: '作者' },
      { to: '/stats', label: '统计' },
    ],
  },
  {
    title: '工具与外部服务',
    desc: '格式转换、查重、OPDS、Komga、KOReader 等。',
    links: [
      { to: '/tools', label: '工具箱' },
      { to: '/settings/opds', label: 'OPDS 订阅源' },
      { to: '/settings/komga', label: 'Komga' },
    ],
  },
]
</script>

<template>
  <div>
    <PageHead title="帮助" desc="Documentation · 应用内导航与说明" />

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <Card v-for="s in sections" :key="s.title" padding="none">
        <div class="px-4 py-3">
          <div class="text-[13px] font-semibold text-foreground">{{ s.title }}</div>
          <p class="mt-0.5 text-[11.5px] text-muted-foreground">{{ s.desc }}</p>
          <div class="mt-2.5 flex flex-wrap gap-2">
            <RouterLink
              v-for="l in s.links"
              :key="l.to"
              :to="l.to"
              class="rounded-md border border-border bg-muted px-2.5 py-1 text-[12px] text-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              {{ l.label }}
            </RouterLink>
          </div>
        </div>
      </Card>
    </div>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        更完整的迁移对照与采集证据见仓库内
        <code class="font-mono text-foreground">docs/</code> 目录（设置页清单、能力缺口、路线图核查等）。
      </div>
    </Card>
  </div>
</template>
