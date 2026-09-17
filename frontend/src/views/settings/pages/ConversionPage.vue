<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import { CONVERSION_FIELDS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'

/**
 * EXTENSIONS → Conversion（`/settings/ext/conversion`）
 *
 * 本项目独有分区：上游 BookOrbit 不做 TXT → EPUB 转换，因此没有对应设置页。
 * 与上游分区明确隔离，避免后续对齐时被误删（迁移要点 5）。
 */

const { cfg, files, capabilities, calibreOk, saving, val, setVal, loadConfig, saveSection } =
  useSettingsConfig()

onMounted(() => loadConfig())
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">转换</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Conversion</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">章节识别与元数据处理</span>
      <Button
        size="sm"
        variant="primary"
        class="ml-auto"
        :disabled="saving"
        @click="saveSection('conversion')"
      >保存</Button>
    </div>

    <Card padding="none" class="mb-4">
      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in CONVERSION_FIELDS"
          :key="f.path"
          :field="f"
          :value="val(f.path)"
          @update="setVal(f.path, $event)"
        />

        <div class="flex items-center gap-4 px-4 py-3">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-1.5">
              <span class="text-[13px] font-medium text-foreground">输出格式</span>
              <Badge :tone="calibreOk ? 'ok' : 'warn'">
                {{ calibreOk ? 'Calibre 可用' : '未装 Calibre' }}
              </Badge>
            </div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground">
              EPUB 始终生成（在线阅读基础）；选 MOBI / AZW3 时额外用 Calibre 派生
            </div>
            <div
              v-if="(cfg.output.format || 'epub') !== 'epub' && !calibreOk"
              class="mt-1 text-[11px] text-warning"
            >
              未检测到 ebook-convert，转换时会自动降级为 EPUB（可设环境变量
              {{ capabilities?.ebook_convert.env_var || 'EBOOK_CONVERT_BIN' }} 或安装 Calibre）
            </div>
          </div>
          <select
            :value="cfg.output.format || 'epub'"
            class="h-8 shrink-0 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
            @change="setVal('output.format', ($event.target as HTMLSelectElement).value)"
          >
            <option value="epub">EPUB</option>
            <option value="mobi">MOBI</option>
            <option value="azw3">AZW3</option>
          </select>
        </div>
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <p class="text-[11.5px] text-muted-foreground">
      保存写入 <code class="font-mono">{{ files.settings_file }}</code>（叠加在
      <code class="font-mono">{{ files.config_file }}</code> 之上，不改动其注释）。
    </p>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        本页在上游 BookOrbit 中<strong>没有对应设置页</strong>——上游不做 TXT → EPUB 转换。
        它属于本项目相对上游的核心差异，对齐迁移时保留，不随上游改名。
        转换产出的成品目录语义见
        <RouterLink to="/settings/library/maintenance" class="underline">书库 → 维护</RouterLink>。
      </div>
    </Card>
  </div>
</template>
