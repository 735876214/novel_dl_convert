<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import Segment from '@/components/ui/Segment.vue'
import SettingsUnsupportedCard from '@/views/settings/SettingsUnsupportedCard.vue'
import {
  NOTIFY_CATEGORIES,
  NOTIFY_LEVELS,
  NOTIFY_PREFS_DEFAULT,
  readNotifyPrefs,
  saveNotifyPrefs,
  type NotifyLevel,
  type NotifyPrefs,
} from '@/lib/notifyPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * YOU → Notifications（`/settings/account/notifications`）
 *
 * 真实实现：按「活动类别」设置 Off / 仅失败 / 全部。
 * 与上游的**关键差异**：上游是服务端投递（可走邮件），本项目没有投递渠道，
 * 这里的开关做的是**客户端过滤**，生效范围就是通知中心与日志看到的条目。
 * 页面上如实标注了这一点，避免用户误以为能控制邮件。
 */

const ui = useUiStore()
const prefs = ref<NotifyPrefs>(readNotifyPrefs())

const LEVEL_OPTIONS = NOTIFY_LEVELS.map((l) => ({ value: l.value, label: l.label }))

function setLevel(id: string, v: string): void {
  prefs.value = { ...prefs.value, [id]: v as NotifyLevel }
  saveNotifyPrefs(prefs.value)
  const cat = NOTIFY_CATEGORIES.find((c) => c.id === id)
  const lv = NOTIFY_LEVELS.find((l) => l.value === v)
  ui.toast(`${cat?.label ?? id}：${lv?.label ?? v}`)
}

function reset(): void {
  prefs.value = { ...NOTIFY_PREFS_DEFAULT }
  saveNotifyPrefs(prefs.value)
  ui.toast('已恢复默认通知偏好')
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">通知</h2>
      <span class="font-mono text-[11.5px] text-muted-foreground">Notifications</span>
      <Button size="sm" class="ml-auto" @click="reset">恢复默认</Button>
    </div>

    <!-- 语义差异提示：这里是客户端过滤，不是投递开关 -->
    <Card class="mb-4">
      <div class="flex gap-2.5">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
        <div class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-muted-foreground">
          <p>
            <span class="text-foreground">本项目没有服务端通知投递</span> ——
            「通知」就是活动日志的一个视图。因此这里的开关是
            <span class="text-foreground">客户端过滤</span>：设置后，
            <RouterLink to="/notify" class="underline">通知中心</RouterLink>
            只会显示符合规则的条目，失败记录不会被静默丢弃（可随时改回来）。
          </p>
        </div>
      </div>
    </Card>

    <Card padding="none">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">活动类别</h3>
        <p class="mt-1 text-[11.5px] text-muted-foreground">
          共 {{ NOTIFY_CATEGORIES.length }} 类，对应后端活动日志的操作类型。
        </p>
      </div>

      <div
        v-for="c in NOTIFY_CATEGORIES"
        :key="c.id"
        class="flex flex-wrap items-center gap-4 border-b border-border px-4 py-3.5 last:border-b-0"
      >
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-foreground">{{ c.label }}</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">{{ c.desc }}</div>
        </div>
        <Segment
          :options="LEVEL_OPTIONS"
          :model-value="prefs[c.id]"
          @update:model-value="(v: string) => setLevel(c.id, v)"
        />
      </div>
    </Card>

    <p class="mt-3 text-[11px] leading-relaxed text-muted-foreground">
      偏好存在浏览器本地（键 <code class="font-mono">nf-notify-prefs</code>），
      换设备不会同步 —— 这与上游「存账号」不同，属未支持范围。
    </p>

    <SettingsUnsupportedCard
      label="Notifications"
      :groups="['LIBRARY', 'FILES', 'INTEGRATIONS', 'PERSONAL', 'APP UPDATES']"
      :items="[
        '上游按「事件类型」分类（Library scanning / Metadata fetching / Author enrichment / File write-back / Book requests / Email delivery 等 10 类）',
        '上游的『跳过』类别：本项目 activity_log 定义了该动作但目前没有写入点',
        '上游的级别还控制后端行为（如是否推送邮件），本项目仅前端过滤',
        'Achievements（成就通知）',
        'Show What\'s New after updates（更新后弹出新功能提示）',
        '通知偏好存账号（多设备同步）',
      ]"
      note="本页把上游的「事件类型」映射为本项目的日志操作类型（转换 / 添加 / 重命名 / 清理），语义相近但不等价：本项目没有元数据抓取、成就、邮件投递等事件源。"
    />
  </div>
</template>
