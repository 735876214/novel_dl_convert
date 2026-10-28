<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type Podcast, type PodcastEpisode } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 播客（第 173 期）：订阅 / 刷新 / 浏览单集 / 直接试听。
 *
 * 为什么不是「书库」：书库在本项目里是**要被扫描的目录**，而播客是远端 RSS ——
 * 没有目录可扫。所以这里是一套独立的订阅子系统（自己的表、自己的页面），
 * 与书架 / 书目零耦合。
 *
 * 出网只在两个用户动作里发生：**订阅**与**刷新**。单集音频由浏览器直接从发布方
 * 服务器流式播放（`<audio preload="none">`），本应用不转存 —— 省磁盘，也避免
 * 「下载了一堆其实不会再听的音频」。
 */
const ui = useUiStore()

const pods = ref<Podcast[]>([])
const episodes = ref<PodcastEpisode[]>([])
const selected = ref<string>('')
const feedUrl = ref('')
const loading = ref(true)
const busy = ref('')
const error = ref('')

const selectedPodcast = computed(() => pods.value.find((p) => p.id === selected.value) || null)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    pods.value = (await api.podcasts()).items
    if (selected.value && !pods.value.some((p) => p.id === selected.value)) {
      selected.value = ''
      episodes.value = []
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取订阅失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function subscribe(): Promise<void> {
  const url = feedUrl.value.trim()
  if (!url || busy.value) return
  busy.value = 'subscribe'
  error.value = ''
  try {
    const r = await api.subscribePodcast(url)
    ui.toast(r.created
      ? `已订阅「${r.podcast.title}」：新增 ${r.added} 集`
      : `已刷新「${r.podcast.title}」：新增 ${r.added} 集`)
    feedUrl.value = ''
    await load()
    await open(r.podcast.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '订阅失败'
  } finally {
    busy.value = ''
  }
}

async function refresh(p: Podcast): Promise<void> {
  if (busy.value) return
  busy.value = `refresh:${p.id}`
  error.value = ''
  try {
    const r = await api.refreshPodcast(p.id)
    ui.toast(`「${p.title}」：新增 ${r.added} 集，更新 ${r.updated} 集`)
    await load()
    if (selected.value === p.id) await open(p.id)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '刷新失败'
  } finally {
    busy.value = ''
  }
}

async function remove(p: Podcast): Promise<void> {
  if (busy.value) return
  busy.value = `del:${p.id}`
  try {
    await api.deletePodcast(p.id)
    ui.toast(`已移除订阅「${p.title}」`)
    if (selected.value === p.id) {
      selected.value = ''
      episodes.value = []
    }
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '移除失败'
  } finally {
    busy.value = ''
  }
}

async function open(id: string): Promise<void> {
  selected.value = id
  episodes.value = []
  try {
    episodes.value = (await api.podcastEpisodes(id)).items
  } catch (e) {
    error.value = e instanceof Error ? e.message : '读取单集失败'
  }
}

function fmtDuration(sec: number): string {
  if (!sec) return ''
  const h = Math.floor(sec / 3600)
  const m = Math.floor(sec % 3600 / 60)
  const s = sec % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

function fmtDate(ts: number): string {
  if (!ts) return '未知时间'
  return new Date(ts * 1000).toLocaleDateString()
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">播客</h2>
      <span class="text-[11.5px] text-muted-foreground">
        订阅 RSS 播客源；单集由浏览器直接从发布方播放，不转存
      </span>
    </div>

    <Card>
      <div class="flex flex-wrap items-end gap-2">
        <label class="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span class="text-[11px] text-muted-foreground">RSS 地址</span>
          <input
            v-model="feedUrl"
            type="url"
            aria-label="RSS 地址"
            placeholder="https://example.com/feed.xml"
            class="h-8 rounded-md border border-border bg-card px-2 text-[12px] text-foreground outline-none focus:border-ring"
            @keyup.enter="subscribe"
          >
        </label>
        <Button size="sm" variant="primary" :disabled="!!busy || !feedUrl.trim()" @click="subscribe">
          {{ busy === 'subscribe' ? '订阅中…' : '订阅' }}
        </Button>
      </div>
      <p class="mt-1.5 text-[11px] text-muted-foreground">
        只支持 RSS 2.0（含 iTunes 扩展）；Atom 源会如实拒绝。同一地址重复订阅 = 刷新。
      </p>
      <p v-if="error" class="mt-1.5 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <div v-if="loading" class="py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

    <EmptyState
      v-else-if="!pods.length"
      icon="volume"
      title="还没有订阅"
      desc="把播客的 RSS 地址填到上面，就能在这里浏览单集并试听。"
    />

    <template v-else>
      <Card padding="none">
        <ul class="divide-y divide-border">
          <li
            v-for="p in pods"
            :key="p.id"
            class="flex flex-wrap items-center gap-3 px-4 py-3"
            :class="p.id === selected ? 'bg-muted/40' : ''"
          >
            <img
              v-if="p.artwork_url"
              :src="p.artwork_url"
              alt=""
              referrerpolicy="no-referrer"
              class="h-12 w-12 shrink-0 rounded-md border border-border object-cover"
            >
            <div v-else class="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
              <Icon name="volume" class="h-4 w-4 text-muted-foreground" />
            </div>
            <div class="min-w-0 flex-1">
              <button type="button" class="cursor-pointer truncate text-left text-[13px] font-medium text-foreground hover:text-primary" @click="open(p.id)">
                {{ p.title }}
              </button>
              <div class="mt-0.5 truncate text-[11.5px] text-muted-foreground">
                {{ p.author || '未知作者' }}
                <span v-if="p.categories.length"> · {{ p.categories.join('、') }}</span>
                <span v-if="p.last_fetched_at"> · 上次刷新 {{ fmtDate(p.last_fetched_at) }}</span>
              </div>
            </div>
            <div class="flex shrink-0 gap-1">
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="open(p.id)">
                {{ p.id === selected ? '收起' : '单集' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="refresh(p)">
                {{ busy === `refresh:${p.id}` ? '刷新中…' : '刷新' }}
              </Button>
              <Button size="sm" variant="ghost" :disabled="!!busy" @click="remove(p)">移除</Button>
            </div>
          </li>
        </ul>
      </Card>

      <Card v-if="selectedPodcast">
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">
          {{ selectedPodcast.title }} · 单集
          <span class="ml-1 text-[11px] font-normal text-muted-foreground">共 {{ episodes.length }} 集</span>
        </h3>
        <EmptyState
          v-if="!episodes.length"
          icon="volume"
          title="还没有单集"
          desc="点上面的「刷新」去发布方那里取最新一期。"
        />
        <ul v-else class="divide-y divide-border">
          <li v-for="e in episodes" :key="e.id" class="py-2.5">
            <div class="flex flex-wrap items-baseline gap-2">
              <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground">{{ e.title }}</span>
              <span class="shrink-0 text-[11px] text-muted-foreground">{{ fmtDate(e.published_at) }}</span>
              <span v-if="e.duration_sec" class="shrink-0 text-[11px] text-muted-foreground tabular-nums">
                {{ fmtDuration(e.duration_sec) }}
              </span>
            </div>
            <p v-if="e.description" class="mt-0.5 line-clamp-2 text-[11.5px] leading-relaxed text-muted-foreground">
              {{ e.description }}
            </p>
            <audio
              v-if="e.audio_url"
              controls
              preload="none"
              :src="e.audio_url"
              class="mt-1.5 h-8 w-full"
            />
          </li>
        </ul>
      </Card>
    </template>
  </div>
</template>
