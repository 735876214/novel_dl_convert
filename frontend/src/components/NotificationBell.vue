<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type NotificationItem } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 顶栏通知浮层（对应上游顶栏的 Notifications）。
 *
 * 与整页 `/notify` 同数据源（`/api/notifications`），差别是这里只取最近几条。
 *
 * ⚠️ 角标用的是后端的 **`unread_total`（全量未读数）**，不能用本页的 `unread` ——
 * 后者只是「当前这一页里的未读数」，日志一多就会少算，角标随之失真。
 */
const ui = useUiStore()
const router = useRouter()

const open = ref(false)
const items = ref<NotificationItem[]>([])
const unread = ref(0)
const loading = ref(false)
const busy = ref(false)
const wrap = ref<HTMLElement | null>(null)

const badge = computed(() => (unread.value > 99 ? '99+' : String(unread.value)))

const ICON_BTN =
  'grid h-[2.0625rem] w-[2.0625rem] cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'

async function load(): Promise<void> {
  loading.value = true
  try {
    const r = await api.notifications(8)
    items.value = r.items
    unread.value = r.unread_total
  } catch {
    // 浮层取不到数据时不打扰用户：角标保持原值
  }
  loading.value = false
}

async function toggle(): Promise<void> {
  open.value = !open.value
  if (open.value) await load()
}

async function markAll(): Promise<void> {
  busy.value = true
  try {
    const r = await api.markNotificationsRead({ all: true })
    ui.toast(r.marked ? `已标记 ${r.marked} 条为已读` : '没有新的未读通知')
    await load()
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '标记失败')
  } finally {
    busy.value = false
  }
}

async function markOne(n: NotificationItem): Promise<void> {
  if (n.read) return
  try {
    await api.markNotificationsRead({ ids: [n.id] })
    await load()
  } catch {
    // 单条标记失败不提示：下次打开会重新加载
  }
}

function goAll(): void {
  open.value = false
  router.push('/notify')
}

/** 点浮层外部关闭 */
function onDocClick(e: MouseEvent): void {
  if (!open.value) return
  const t = e.target as Node
  if (wrap.value && !wrap.value.contains(t)) open.value = false
}

/** Esc 关闭（与任务抽屉一致） */
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') open.value = false
}

onMounted(() => {
  void load()
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKey)
})

onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <div ref="wrap" class="relative">
    <button
      :class="[ICON_BTN, open ? 'bg-[var(--shell-accent-tint)] text-primary hover:text-primary' : '']"
      type="button"
      title="通知"
      aria-label="通知"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <Icon name="bell" class="h-[17px] w-[17px]" />
      <!-- 未读角标 -->
      <span
        v-if="unread > 0"
        class="pointer-events-none absolute -top-0.5 -right-0.5 min-w-[1rem] rounded-full bg-destructive px-1 text-[9.5px] leading-4 font-semibold text-white tabular-nums"
      >
        {{ badge }}
      </span>
    </button>

    <!-- 浮层：点按钮切换，点外部 / Esc 关闭 -->
    <div
      v-if="open"
      class="absolute top-[calc(100%+0.5rem)] right-0 z-50 w-[min(22rem,88vw)] overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-2xl backdrop-blur-md backdrop-saturate-150"
    >
      <div class="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
        <h3 class="text-[13px] font-semibold text-foreground">通知</h3>
        <span v-if="unread" class="text-[11px] text-muted-foreground">未读 {{ unread }} 条</span>
        <Button
          size="sm"
          variant="ghost"
          class="ml-auto"
          :disabled="busy || unread === 0"
          @click.stop="markAll"
        >
          全部已读
        </Button>
      </div>

      <div class="max-h-[min(24rem,60vh)] overflow-y-auto">
        <div v-if="loading" class="px-4 py-8 text-center text-[12px] text-muted-foreground">加载中…</div>

        <template v-else-if="items.length">
          <div
            v-for="n in items"
            :key="n.id"
            class="flex cursor-pointer items-start gap-2.5 border-b border-border/60 px-3.5 py-2.5 transition-colors last:border-b-0 hover:bg-muted/60"
            :class="n.read ? 'opacity-60' : ''"
            @click.stop="markOne(n)"
          >
            <span
              class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full"
              :class="n.status === '失败' ? 'bg-destructive/14 text-destructive' : 'bg-success/14 text-success'"
            >
              <Icon :name="n.status === '失败' ? 'alert' : 'check'" class="h-3 w-3" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex items-baseline gap-1.5">
                <span v-if="!n.read" class="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                <span class="truncate text-[12px] font-medium text-foreground">{{ n.action || '活动' }}</span>
                <span class="ml-auto shrink-0 text-[10.5px] text-muted-foreground tabular-nums">{{ n.ts }}</span>
              </div>
              <div class="truncate text-[11.5px] text-foreground/85">{{ n.file }}</div>
              <!-- detail 只在「失败」时才是错误原因；成功条目的 detail 是备注，不能染成红色 -->
              <div
                v-if="n.detail"
                class="mt-0.5 truncate text-[10.5px]"
                :class="n.status === '失败' ? 'text-destructive' : 'text-muted-foreground'"
              >
                {{ n.detail }}
              </div>
            </div>
          </div>
        </template>

        <div v-else class="px-4 py-8 text-center text-[12px] text-muted-foreground">
          暂无通知
        </div>
      </div>

      <div class="border-t border-border p-2">
        <Button variant="ghost" block @click.stop="goAll">查看全部通知</Button>
      </div>
    </div>
  </div>
</template>
