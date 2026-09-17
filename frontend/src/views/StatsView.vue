<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import Card from '@/components/ui/Card.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type StatsOverview, type StatsTop } from '@/lib/api'

/**
 * 数据统计：书库规模、阅读状态分布、入库/阅读节奏（窗口可选 7/28/90 天）、
 * 最近在读、Top 作者/系列/出版社/题材、年份分布与书库体检。
 *
 * 这里**不走 stats store**：store 是 dashboard 的一次性缓存（固定 28 天），
 * 本页的窗口切换若写回 store，dashboard 的「近 28 天」标注就会失真。
 */
const router = useRouter()

const data = ref<StatsOverview | null>(null)
const days = ref(28)
const loading = ref(false)

async function load(): Promise<void> {
  loading.value = true
  try {
    data.value = await api.stats(days.value)
  } catch {
    /* 未登录或后端不可用时保持为空 */
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(days, load)

const DAY_OPTIONS = [7, 28, 90] as const

const s = computed(() => data.value)

function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

const formats = computed(() =>
  Object.entries(s.value?.books.by_format ?? {}).sort((a, b) => b[1] - a[1]),
)

const reading = computed(() => s.value?.reading ?? { unread: 0, reading: 0, finished: 0, annotations: 0 })
const readingTotal = computed(
  () => reading.value.unread + reading.value.reading + reading.value.finished || 1,
)
const readingBars = computed(() => [
  { label: '未读', value: reading.value.unread, cls: 'bg-muted-foreground/45' },
  { label: '在读', value: reading.value.reading, cls: 'bg-primary/70' },
  { label: '已读完', value: reading.value.finished, cls: 'bg-success' },
])

const rhythm = computed(() => s.value?.added_28d ?? [])
const rhythmPeak = computed(() => Math.max(1, ...rhythm.value))
function rhythmHeight(n: number): string {
  if (n <= 0) return '3%'
  return `${Math.max(8, (n / rhythmPeak.value) * 100).toFixed(1)}%`
}

/** 阅读时长（秒）→ 可读文案 */
function fmtDuration(seconds: number): string {
  if (!seconds) return '0 分'
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${Math.max(1, m)} 分`
}

const readRhythm = computed(() => s.value?.reading_28d ?? [])
const readPeak = computed(() => Math.max(1, ...readRhythm.value))
function readHeight(n: number): string {
  if (n <= 0) return '3%'
  return `${Math.max(8, (n / readPeak.value) * 100).toFixed(1)}%`
}
const readTotal = computed(() => readRhythm.value.reduce((a, b) => a + b, 0))

// ---- Top 榜：默认 8 条，可展开到服务端返回的全部（最多 50）----
const expanded = ref<Record<string, boolean>>({})
function topItems(key: string, items: StatsTop[] | undefined): StatsTop[] {
  const all = items ?? []
  return expanded.value[key] ? all : all.slice(0, 8)
}
function toggleTop(key: string): void {
  expanded.value[key] = !expanded.value[key]
}
function hasMore(items: StatsTop[] | undefined): boolean {
  return (items?.length ?? 0) > 8
}

// ---- 年份分布（十年一档）----
const decadePeak = computed(() =>
  Math.max(1, ...(s.value?.years.decades ?? []).map((d) => d.count)),
)

// ---- 书库体检 ----
const integrity = computed(() => {
  const g = s.value?.integrity
  if (!g) return []
  const rows = [
    { key: 'missing_author', label: '缺作者' },
    { key: 'missing_language', label: '缺语言' },
    { key: 'no_cover', label: '无封面' },
    { key: 'zero_size', label: '0 字节' },
    { key: 'unparsable', label: '解析失败' },
  ]
  return rows.map((r) => ({ ...r, count: g[r.key as keyof typeof g] ?? 0 }))
})
const integrityTotal = computed(() =>
  integrity.value.reduce((a, r) => a + r.count, 0),
)
</script>

<template>
  <div>
    <PageHead title="数据统计" desc="书库规模、阅读状态、入库节奏与书库体检" />

    <!-- 节奏图窗口切换（PageHead 无插槽，放在页头下方） -->
    <div class="-mt-3 mb-3 flex gap-1">
      <button
        v-for="d in DAY_OPTIONS"
        :key="d"
        type="button"
        class="cursor-pointer rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors"
        :class="days === d
          ? 'bg-primary text-primary-foreground'
          : 'bg-muted text-muted-foreground hover:text-foreground'"
        @click="days = d"
      >
        近 {{ d }} 天
      </button>
    </div>

    <div v-if="!s" class="py-20 text-center text-[13px] text-muted-foreground">
      {{ loading ? '加载中…' : '暂无数据' }}
    </div>

    <template v-else>
      <!-- 规模卡片 -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Card v-for="c in [
          { label: '书籍', value: String(s.books.total), icon: 'book' },
          { label: '占用', value: fmtBytes(s.books.size), icon: 'file' },
          { label: '作者', value: String(s.authors.total), icon: 'users' },
          { label: '系列', value: String(s.series.total), icon: 'layers' },
          { label: '平均进度', value: `${Math.round(s.avg_progress)}%`, icon: 'chart' },
          { label: '阅读时长', value: fmtDuration(s.reading.seconds), icon: 'clock' },
        ]" :key="c.label">
          <div class="flex items-center gap-2 text-muted-foreground">
            <Icon :name="c.icon" class="h-3.5 w-3.5" />
            <span class="text-[11.5px]">{{ c.label }}</span>
          </div>
          <div class="mt-1.5 text-[22px] leading-none font-semibold text-foreground tabular-nums">
            {{ c.value }}
          </div>
        </Card>
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- 阅读状态 -->
        <Card>
          <h3 class="mb-3 text-[13px] font-semibold text-foreground">阅读状态</h3>

          <div class="flex h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              v-for="b in readingBars"
              :key="b.label"
              :class="b.cls"
              :style="{ width: `${(b.value / readingTotal) * 100}%` }"
            />
          </div>

          <div class="mt-3 grid grid-cols-3 gap-2">
            <div v-for="b in readingBars" :key="b.label" class="text-center">
              <div class="text-[17px] font-semibold text-foreground tabular-nums">{{ b.value }}</div>
              <div class="text-[11px] text-muted-foreground">{{ b.label }}</div>
            </div>
          </div>

          <div class="mt-4 flex items-center justify-between border-t border-border pt-3">
            <span class="text-[12px] text-muted-foreground">批注 / 高亮</span>
            <span class="text-[13px] font-semibold text-foreground tabular-nums">{{ reading.annotations }}</span>
          </div>

          <div class="mt-3 flex flex-wrap gap-1.5">
            <span
              v-for="[fmt, n] in formats"
              :key="fmt"
              class="rounded bg-muted px-2 py-0.5 text-[11px] text-muted-foreground tabular-nums"
            >
              {{ fmt }} · {{ n }}
            </span>
          </div>
        </Card>

        <!-- 入库节奏 -->
        <Card>
          <div class="flex items-baseline justify-between">
            <h3 class="text-[13px] font-semibold text-foreground">入库节奏</h3>
            <span class="text-[11px] text-muted-foreground tabular-nums">
              近 {{ s.window }} 天 · 共 {{ rhythm.reduce((a, b) => a + b, 0) }} 本
            </span>
          </div>
          <div class="mt-3 flex h-[104px] items-end gap-[3px]">
            <div
              v-for="(n, i) in rhythm"
              :key="i"
              class="min-w-0 flex-1 rounded-[2px]"
              :class="n > 0 ? 'bg-primary/85' : 'bg-muted'"
              :style="{ height: rhythmHeight(n) }"
              :title="`${s.window - 1 - i} 天前：${n} 本`"
            />
          </div>
        </Card>

        <!-- 阅读时长节奏 -->
        <Card>
          <div class="flex items-baseline justify-between">
            <h3 class="text-[13px] font-semibold text-foreground">阅读时长</h3>
            <span class="text-[11px] text-muted-foreground tabular-nums">
              近 {{ s.window }} 天 · {{ fmtDuration(readTotal) }}
            </span>
          </div>
          <div class="mt-3 flex h-[104px] items-end gap-[3px]">
            <div
              v-for="(n, i) in readRhythm"
              :key="i"
              class="min-w-0 flex-1 rounded-[2px]"
              :class="n > 0 ? 'bg-primary/85' : 'bg-muted'"
              :style="{ height: readHeight(n) }"
              :title="`${s.window - 1 - i} 天前：${Math.round(n / 60)} 分`"
            />
          </div>
          <p class="mt-2 text-[11.5px] text-muted-foreground">
            共 <span class="font-semibold text-foreground tabular-nums">{{ s.reading.sessions }}</span> 次会话 ·
            平均每次 <span class="font-semibold text-foreground tabular-nums">{{ fmtDuration(s.reading.avg_seconds) }}</span>
          </p>
        </Card>
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
        <!-- 最近在读 -->
        <Card class="lg:col-span-1">
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">最近在读</h3>
          <p v-if="!s.recent.length" class="text-[12px] text-muted-foreground">还没有阅读记录。</p>
          <button
            v-for="r in s.recent"
            :key="r.id"
            type="button"
            class="flex w-full cursor-pointer items-center gap-2.5 rounded-md px-1 py-1.5 text-left transition-colors hover:bg-muted"
            @click="router.push(`/read/${r.id}`)"
          >
            <div class="min-w-0 flex-1">
              <div class="truncate text-[12.5px] text-foreground">{{ r.title }}</div>
              <div class="mt-1 h-1 w-full overflow-hidden rounded-full bg-muted">
                <div class="h-full rounded-full bg-primary" :style="{ width: `${r.percent}%` }" />
              </div>
            </div>
            <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">
              {{ Math.round(r.percent) }}%
            </span>
          </button>
        </Card>

        <!-- Top 作者 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">Top 作者</h3>
          <p v-if="!s.authors.top.length" class="text-[12px] text-muted-foreground">暂无数据。</p>
          <div
            v-for="a in topItems('authors', s.authors.top)"
            :key="a.name"
            class="flex items-center gap-2 border-b border-border/60 py-1.5 last:border-b-0"
          >
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ a.name }}</span>
            <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ a.count }}</span>
          </div>
          <button
            v-if="hasMore(s.authors.top)"
            type="button"
            class="mt-1.5 cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="toggleTop('authors')"
          >
            {{ expanded.authors ? '收起' : `展开全部 ${s.authors.top.length} 位` }}
          </button>
        </Card>

        <!-- Top 系列 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">Top 系列</h3>
          <p v-if="!s.series.top.length" class="text-[12px] text-muted-foreground">暂无数据。</p>
          <button
            v-for="x in topItems('series', s.series.top)"
            :key="x.name"
            type="button"
            class="flex w-full cursor-pointer items-center gap-2 border-b border-border/60 py-1.5 text-left last:border-b-0 hover:text-primary"
            @click="router.push(`/series/${encodeURIComponent(x.name)}`)"
          >
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ x.name }}</span>
            <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ x.count }}</span>
          </button>
          <button
            v-if="hasMore(s.series.top)"
            type="button"
            class="mt-1.5 cursor-pointer text-left text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="toggleTop('series')"
          >
            {{ expanded.series ? '收起' : `展开全部 ${s.series.top.length} 个` }}
          </button>
        </Card>
      </div>

      <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <!-- Top 出版社 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">Top 出版社</h3>
          <p v-if="!s.publishers.top.length" class="text-[12px] text-muted-foreground">暂无数据。</p>
          <div
            v-for="p in topItems('publishers', s.publishers.top)"
            :key="p.name"
            class="flex items-center gap-2 border-b border-border/60 py-1.5 last:border-b-0"
          >
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ p.name }}</span>
            <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ p.count }}</span>
          </div>
          <button
            v-if="hasMore(s.publishers.top)"
            type="button"
            class="mt-1.5 cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="toggleTop('publishers')"
          >
            {{ expanded.publishers ? '收起' : `展开全部 ${s.publishers.top.length} 家` }}
          </button>
        </Card>

        <!-- Top 题材 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">Top 题材</h3>
          <p v-if="!s.genres.top.length" class="text-[12px] text-muted-foreground">暂无数据。</p>
          <div
            v-for="g in topItems('genres', s.genres.top)"
            :key="g.name"
            class="flex items-center gap-2 border-b border-border/60 py-1.5 last:border-b-0"
          >
            <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ g.name }}</span>
            <span class="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ g.count }}</span>
          </div>
          <button
            v-if="hasMore(s.genres.top)"
            type="button"
            class="mt-1.5 cursor-pointer text-[11.5px] text-muted-foreground hover:text-foreground"
            @click="toggleTop('genres')"
          >
            {{ expanded.genres ? '收起' : `展开全部 ${s.genres.top.length} 类` }}
          </button>
        </Card>

        <!-- 年份分布 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">出版年份</h3>
          <p v-if="!s.years.decades.length" class="text-[12px] text-muted-foreground">
            书目里没有可解析的出版年份。
          </p>
          <template v-else>
            <div v-for="d in s.years.decades" :key="d.decade" class="mb-1.5 flex items-center gap-2">
              <span class="w-12 shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ d.decade }}s</span>
              <div class="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-primary/70"
                  :style="{ width: `${(d.count / decadePeak) * 100}%` }"
                />
              </div>
              <span class="w-7 shrink-0 text-right text-[11px] text-muted-foreground tabular-nums">{{ d.count }}</span>
            </div>
            <p v-if="s.years.unknown" class="mt-2 text-[11px] text-muted-foreground">
              另有 {{ s.years.unknown }} 本未标注年份。
            </p>
          </template>
        </Card>

        <!-- 书库体检 -->
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">书库体检</h3>
          <p v-if="!integrityTotal" class="text-[12px] text-muted-foreground">
            没有发现问题 —— 元数据、封面与文件都齐整。
          </p>
          <template v-else>
            <div
              v-for="r in integrity"
              :key="r.key"
              class="flex items-center gap-2 border-b border-border/60 py-1.5 last:border-b-0"
            >
              <span class="min-w-0 flex-1 truncate text-[12.5px]" :class="r.count ? 'text-foreground' : 'text-muted-foreground'">
                {{ r.label }}
              </span>
              <span
                class="shrink-0 text-[11.5px] tabular-nums"
                :class="r.count ? 'font-semibold text-amber-600 dark:text-amber-400' : 'text-muted-foreground'"
              >
                {{ r.count }}
              </span>
            </div>
            <p class="mt-2 text-[11px] text-muted-foreground">缺元数据的书可在详情页「编辑元数据」里补。</p>
          </template>
        </Card>
      </div>
    </template>
  </div>
</template>
