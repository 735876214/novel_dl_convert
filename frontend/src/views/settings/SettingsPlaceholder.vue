<script setup lang="ts">
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import type { SettingsPageDef } from '@/data/settingsNav'

/**
 * 「未支持」占位页。
 *
 * 迁移约定（对齐 `docs/bookorbit-settings-inventory.md` 第 6 节第 3 条）：
 *   - 不做空页面；只读展示上游该页的真实结构（标题 / 说明 / 分组 / 条目）
 *   - 每个条目带「未支持」标注，顶部给出统一说明
 *   - 不伪造交互：所有条目均为只读展示，没有可点的开关
 *   - 本项目已有等价能力时，给出跳转入口
 */
defineProps<{ page: SettingsPageDef }>()
</script>

<template>
  <div>
    <!-- 页头 -->
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">{{ page.zh }}</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">{{ page.label }}</span>
      <Badge tone="warn" class="ml-1">未支持</Badge>
    </div>

    <!-- 统一说明 -->
    <Card class="mb-4">
      <div class="flex gap-2.5">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        <div class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-muted-foreground">
          <p>
            本页对应上游 BookOrbit 的
            <span class="font-mono text-foreground">{{ page.label }}</span>
            页。本项目尚未实现该能力，因此这里只做只读展示。
          </p>
          <p v-if="page.note" class="mt-1 text-foreground/80">{{ page.note }}</p>
          <p v-else class="mt-1">
            下方列出上游该页的分组与设置项，仅作迁移对照，全部不可交互。
          </p>
        </div>
      </div>
    </Card>

    <!-- 上游页面结构 -->
    <Card padding="none" class="mb-4">
      <div class="border-b border-border px-4 py-3">
        <div class="flex flex-wrap items-baseline gap-2">
          <h3 class="text-[13px] font-semibold text-foreground">上游页面结构</h3>
          <span class="font-mono text-[11px] text-muted-foreground">{{ page.upstream?.title }}</span>
        </div>
        <p v-if="page.upstream?.desc" class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
          {{ page.upstream.desc }}
        </p>
      </div>

      <!-- 页内分组 -->
      <div v-if="page.upstream?.groups?.length" class="border-b border-border px-4 py-3">
        <div class="mb-2 text-[11.5px] text-muted-foreground">页内分组</div>
        <div class="flex flex-wrap gap-1.5">
          <span
            v-for="g in page.upstream.groups"
            :key="g"
            class="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
          >{{ g }}</span>
        </div>
      </div>

      <!-- 设置项（只读） -->
      <div v-if="page.upstream?.items?.length">
        <div class="px-4 pt-3 pb-1 text-[11.5px] text-muted-foreground">
          设置项（{{ page.upstream.items.length }} 项，均为只读）
        </div>
        <div
          v-for="(it, i) in page.upstream.items"
          :key="i"
          class="flex items-start gap-3 border-b border-border/60 px-4 py-2 last:border-b-0"
        >
          <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
          <span class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-foreground/90">{{ it }}</span>
          <span class="shrink-0 text-[10.5px] text-muted-foreground">未支持</span>
        </div>
      </div>

      <!-- 采集缺口 -->
      <div v-if="page.upstream?.uncaptured" class="border-t border-border px-4 py-3">
        <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
          <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
          <span>{{ page.upstream.uncaptured }}</span>
        </div>
      </div>
    </Card>

    <!-- 本项目已有等价能力 -->
    <Card v-if="page.link" class="mb-4">
      <div class="flex flex-wrap items-center gap-3">
        <Icon name="arrowRight" class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">本项目已有等价能力</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            该项已实现，但入口不在设置页。为避免功能重复，保持现有入口不变。
          </div>
        </div>
        <RouterLink :to="page.link.to">
          <Button size="sm">{{ page.link.label }}</Button>
        </RouterLink>
      </div>
    </Card>

    <p class="text-[11px] leading-relaxed text-muted-foreground">
      上游逐页采集记录见
      <code class="font-mono">docs/bookorbit-settings-inventory.md</code>；
      截图见 <code class="font-mono">docs/review/bookorbit-settings-shots/</code>。
    </p>
  </div>
</template>
