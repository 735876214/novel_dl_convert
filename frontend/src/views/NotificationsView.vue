<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type NotificationItem } from '@/lib/api'
import { applyNotifyPrefs, hiddenByPrefs, readNotifyPrefs, type NotifyPrefs } from '@/lib/notifyPrefs'
import { useUiStore } from '@/stores/ui'

/**
 * 通知中心：活动日志 + **服务端已读态**。
 *
 * 已读标记存在后端（`notifications_read` 表），多端一致。
 * 条目的稳定 id 由后端按「毫秒时间戳 + 动作 + 文件名 + 结果」生成指纹 ——
 * 日志本身是追加写的 jsonl，没有自增主键。
 *
 * 显示范围仍受「设置 → 通知」的类别偏好约束（客户端过滤），
 * 被过滤掉的条数会明确提示，避免用户以为记录丢失。
 */
const ui = useUiStore()
const items = ref<NotificationItem[]>([])
const loading = ref(true)
const busy = ref(false)
const filter = ref<'all' | 'fail' | 'ok'>('all')
const prefs = ref<NotifyPrefs>(readNotifyPrefs())

async function load(): Promise<void> {
  loading.value = true
  try {
    items.value = (await api.notifications(200)).items
  } catch {
    items.value = []
  }
  loading.value = false
}

onMounted(() => {
  // 每次进入都重读偏好：用户可能刚从设置页改完再回来
  prefs.value = readNotifyPrefs()
  void load()
})

/** 先过类别偏好，再过结果标签 */
const visible = computed(() => applyNotifyPrefs(items.value, prefs.value))
const hiddenCount = computed(() => hiddenByPrefs(items.value, prefs.value))

const failCount = computed(() => visible.value.filter((i) => i.status === '失败').length)
const unreadCount = computed(() => visible.value.filter((i) => !i.read).length)

const filtered = computed(() => {
  if (filter.value === 'fail') return visible.value.filter((i) => i.status === '失败')
  if (filter.value === 'ok') return visible.value.filter((i) => i.status === '成功')
  return visible.value
})

function str(i: NotificationItem, k: string): string {
  const v = (i as unknown as Record<string, unknown>)[k]
  return v === undefined || v === null ? '' : String(v)
}

async function markRead(target: NotificationItem | 'all'): Promise<void> {
  busy.value = true
  try {
    const r =
      target === 'all'
        ? await api.markNotificationsRead({ all: true })
        : await api.markNotificationsRead({ ids: [target.id] })
    ui.toast(r.marked ? `已标记 ${r.marked} 条为已读` : '没有新的未读通知')
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '标记失败')
  } finally {
    busy.value = false
  }
}

const TABS = [
  { key: 'all', label: '全部' },
  { key: 'fail', label: '失败' },
  { key: 'ok', label: '成功' },
] as const
</script>

<template>
  <div>
    <div class="mb-4 flex flex-wrap items-center gap-2">
      <PageHead
        title="通知中心"
        :desc="`未读 ${unreadCount} 条 · 显示 ${visible.length} 条 · 失败 ${failCount} 条`"
      />
      <Button
        size="sm"
        class="ml-auto"
        :disabled="busy || unreadCount === 0"
        @click="markRead('all')"
      >
        全部已读
      </Button>
    </div>

    <!-- 被类别偏好过滤时的提示：避免用户以为记录丢失 -->
    <Card v-if="hiddenCount" class="mb-4" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[11.5px] text-muted-foreground">
        <Icon name="bell" class="h-3.5 w-3.5 shrink-0" />
        <span>另有 {{ hiddenCount }} 条记录被「设置 → 通知」的类别规则隐藏。</span>
        <RouterLink to="/settings/account/notifications" class="ml-auto underline">调整通知设置</RouterLink>
      </div>
    </Card>

    <div class="mb-4 flex flex-wrap gap-1.5">
      <button
        v-for="t in TABS"
        :key="t.key"
        type="button"
        class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="filter === t.key ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground'"
        @click="filter = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <div v-else-if="filtered.length" class="flex flex-col gap-2">
      <Card
        v-for="n in filtered"
        :key="n.id"
        padding="sm"
        class="cursor-pointer transition-opacity"
        :class="n.read ? 'opacity-60' : ''"
        @click="n.read ? undefined : markRead(n)"
      >
        <div class="flex items-start gap-3">
          <span
            class="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full"
            :class="str(n, 'status') === '失败' ? 'bg-destructive/14 text-destructive' : 'bg-success/14 text-success'"
          >
            <Icon :name="str(n, 'status') === '失败' ? 'alert' : 'check'" class="h-3.5 w-3.5" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-baseline gap-2">
              <!-- 未读圆点：已读条目不再显示 -->
              <span v-if="!n.read" class="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="未读" />
              <span class="text-[12.5px] font-medium text-foreground">{{ str(n, 'action') || '活动' }}</span>
              <span class="truncate text-[12.5px] text-foreground">{{ str(n, 'file') }}</span>
              <span class="ml-auto shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ str(n, 'ts') }}</span>
            </div>
            <p v-if="str(n, 'output')" class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
              → {{ str(n, 'output') }}
            </p>
            <p v-if="str(n, 'detail')" class="mt-0.5 text-[11.5px]" :class="str(n, 'status') === '失败' ? 'text-destructive' : 'text-muted-foreground'">
              {{ str(n, 'detail') }}
            </p>
            <p class="mt-0.5 text-[10.5px] text-muted-foreground">
              {{ n.read ? '已读' : '点击标记已读' }}
            </p>
          </div>
        </div>
      </Card>
    </div>

    <EmptyState
      v-else
      icon="bell"
      :title="filter === 'fail' ? '没有失败记录' : '暂无通知'"
      desc="把 txt 放进输入目录，转换与添加的结果会出现在这里。"
    />

    <Card class="mt-4" padding="sm">
      <div class="flex gap-2 text-[11.5px] leading-relaxed text-muted-foreground">
        <Icon name="alert" class="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          已读态存在服务端（<span class="font-mono">notifications_read</span> 表），多端一致；
          清空活动日志时会一并清除已读标记（日志没了，标记也就没有意义）。
          本页仍是<strong>日志视图</strong>，不是上游那种可投递到邮件的服务端通知。
        </span>
      </div>
    </Card>
  </div>
</template>
