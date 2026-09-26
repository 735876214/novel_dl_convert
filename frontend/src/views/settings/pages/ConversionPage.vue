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
 * 本项目独有分区：上游 BookOrbit 不做本地正文解析（分章 / 预处理 / 组装），
 * 因此没有对应设置页。与上游分区明确隔离，避免后续对齐时被误删（迁移要点 5）。
 *
 * 第 62 期起 TXT 走「只入库不转换」（阅读时按需生成派生 EPUB，见 core/txtcache.py），
 * 所以这里只剩**分章与预处理**这些仍然生效的开关；「输出格式」整块删掉了 ——
 * 格式收敛为 epub，没有可选项，留着只是个骗人的下拉框。
 */

const { cfg, files, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

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
      </template>
      <div v-else class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
    </Card>

    <p class="text-[11.5px] text-muted-foreground">
      保存写入 <code class="font-mono">{{ files.settings_file }}</code>（叠加在
      <code class="font-mono">{{ files.config_file }}</code> 之上，不改动其注释）。
    </p>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        本页在上游 BookOrbit 中<strong>没有对应设置页</strong>——上游不做本地正文解析
        （分章 / 预处理 / 组装）。它属于本项目相对上游的核心差异，对齐迁移时保留，不随上游改名。
        投递与入库产出的成品目录语义见
        <RouterLink to="/settings/library/maintenance" class="underline">书库 → 维护</RouterLink>。
      </div>
    </Card>
  </div>
</template>
