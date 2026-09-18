<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import { NETWORK_FIELDS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'

/**
 * EXTENSIONS → Network（`/settings/ext/network`）
 *
 * 本项目独有分区：上游没有书源下载体系，因此没有下载开关 / 公版源限制 / 域名替换等设置。
 */

const { cfg, saving, val, setVal, loadConfig, saveSection, hostReplaceText } = useSettingsConfig()

onMounted(() => loadConfig())
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">网络与下载</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Network</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">下载开关、重试与域名替换</span>
      <Button
        size="sm"
        variant="primary"
        class="ml-auto"
        :disabled="saving"
        @click="saveSection('network')"
      >保存</Button>
    </div>

    <Card padding="none">
      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in NETWORK_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />

        <div class="px-4 py-3">
          <div class="mb-1.5 text-[13px] font-medium text-foreground">域名替换</div>
          <div class="mb-2 text-[11.5px] text-muted-foreground">
            每行一条 <code class="font-mono">old-host=new-host</code>，应对 CDN 漂移
          </div>
          <textarea
            v-model="hostReplaceText"
            rows="4"
            class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          />
        </div>
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        上游的「求书」是「插件 / Torznab 索引器 + 下载客户端」那一套；本项目定位不同，
        从外部获取书一律走
        <RouterLink to="/tools/sources" class="underline">工具 → 书源管理</RouterLink>
        的数据驱动书源规则，因此<strong>不提供「求书」页</strong>（该能力已决策不做）。
      </div>
    </Card>
  </div>
</template>
