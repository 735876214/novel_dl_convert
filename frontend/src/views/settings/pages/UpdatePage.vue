<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import SettingsFieldRow from '@/views/settings/SettingsFieldRow.vue'
import { UPDATE_FIELDS } from '@/data/settingsFields'
import { useSettingsConfig } from '@/composables/useSettingsConfig'

/**
 * EXTENSIONS → Updates（`/settings/ext/update`）
 *
 * 第 78 期新增：版本号单一真值源 + 侧栏版本号 / new 提示 + 一键更新。
 * 第 80 期：四个字段全部接通（新增「更新拉取镜像」）；保存后开关 / 间隔**即时生效**，
 * 不再需要重启进程（后端 `server._apply_update_config`）。
 * 口子仍然只有两个：拉取 `update.image` 指的那一个镜像、重建**自身容器** ——
 * 没有「任意容器 / 任意 exec」（见 core/updater.py）。
 */

const { cfg, files, saving, val, setVal, loadConfig, saveSection } = useSettingsConfig()

onMounted(() => loadConfig())
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">更新</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Updates</span>
      <Badge tone="accent">本项目扩展</Badge>
      <span class="text-[11.5px] text-muted-foreground">版本检查与一键更新</span>
      <Button
        size="sm"
        variant="primary"
        class="ml-auto"
        :disabled="saving"
        @click="saveSection('update')"
      >保存</Button>
    </div>

    <Card padding="none" class="mb-4">
      <template v-if="cfg">
        <SettingsFieldRow
          v-for="f in UPDATE_FIELDS"
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
        版本号来自仓库根 <code class="font-mono">VERSION</code> 文件（单一真值源），侧栏底部与
        <RouterLink to="/whats-new" class="underline">新功能</RouterLink>
        页据此渲染。一键更新须在 <code class="font-mono">docker-compose.yml</code> 的
        <code class="font-mono">volumes</code> 下取消注释
        <code class="font-mono">/var/run/docker.sock</code> 那一行才生效；未挂载时窗口只展示复制升级命令，不做假交互。
      </div>
    </Card>
  </div>
</template>
