<script setup lang="ts">
import { onActivated, ref } from 'vue'
import { RouterLink } from 'vue-router'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, type OpdsEntry, type OpdsFeed, type OpdsSource } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/**
 * OPDS 订阅：把外部的 OPDS 目录当成书源（Komga / Calibre-Web / 标准 OPDS 源）。
 *
 * 与「书源管理」的区别：那边是**网页规则抓取**（解析 HTML、拼章节），
 * 这边是**标准协议订阅**（Atom feed + 下载链接），机制完全不同，故独立成页。
 *
 * 与「设置 → OPDS」的区别：那一页是本应用**对外提供服务**，这一页是**去订阅别人**。
 */
const ui = useUiStore()
const library = useLibraryStore()

const sources = ref<OpdsSource[]>([])
const loading = ref(true)
const busy = ref(false)

/** null = 未在编辑；-1 = 新建；其它 = 编辑该 id */
const editing = ref<number | null>(null)
const form = ref({ name: '', url: '', username: '', password: '' })

const current = ref<OpdsSource | null>(null)
const feed = ref<OpdsFeed | null>(null)
/** 浏览历史（href 栈），用于「返回上一层」——比依赖 feed 的 up 链接更可靠 */
const history = ref<string[]>([])

async function loadSources(): Promise<void> {
  loading.value = true
  try {
    sources.value = (await api.opdsSources()).items
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '加载订阅源失败')
  } finally {
    loading.value = false
  }
}
onActivated(loadSources)

function startCreate(): void {
  editing.value = -1
  form.value = { name: '', url: '', username: '', password: '' }
}

function startEdit(s: OpdsSource): void {
  editing.value = s.id
  // 密码留空：后端把空/掩码解释为「不修改」（改名字时不会把掩码写成新密码）
  form.value = { name: s.name, url: s.url, username: s.username, password: '' }
}

async function save(): Promise<void> {
  busy.value = true
  try {
    if (editing.value === -1) await api.createOpdsSource(form.value)
    else if (editing.value !== null) await api.updateOpdsSource(editing.value, form.value)
    editing.value = null
    await loadSources()
    ui.toast('已保存')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '保存失败')
  } finally {
    busy.value = false
  }
}

async function remove(s: OpdsSource): Promise<void> {
  if (!window.confirm(`删除订阅源「${s.name}」？（不影响已下载的书）`)) return
  try {
    await api.deleteOpdsSource(s.id)
    if (current.value?.id === s.id) {
      current.value = null
      feed.value = null
    }
    await loadSources()
    ui.toast('已删除')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '删除失败')
  }
}

async function open(s: OpdsSource): Promise<void> {
  current.value = s
  feed.value = null
  history.value = []
  await browse('')
}

async function browse(href: string): Promise<void> {
  if (!current.value) return
  busy.value = true
  try {
    feed.value = await api.opdsBrowse(current.value.id, href)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '读取目录失败')
    feed.value = null
  } finally {
    busy.value = false
  }
}

async function enter(entry: OpdsEntry): Promise<void> {
  if (feed.value?.url) history.value.push(feed.value.url)
  await browse(entry.href)
}

async function back(): Promise<void> {
  const prev = history.value.pop()
  await browse(prev ?? '')
}

async function download(entry: OpdsEntry): Promise<void> {
  if (!current.value) return
  busy.value = true
  try {
    const r = await api.opdsDownload(current.value.id, {
      href: entry.href,
      title: entry.title,
      type: entry.type,
      series: entry.series,
    })
    ui.toast(`已下载：${r.name}`)
    await library.loadBooks(true)
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '下载失败')
  } finally {
    busy.value = false
  }
}

function fmtSize(n: number): string {
  if (!n) return ''
  if (n < 1024) return `${n} B`
  if (n < 1048576) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1048576).toFixed(1)} MB`
}
</script>

<template>
  <div>
    <div class="mb-3 flex flex-wrap items-baseline gap-2">
      <h2 class="text-[14px] font-semibold text-foreground">OPDS 订阅</h2>
      <span class="text-[11.5px] text-muted-foreground">
        订阅外部 OPDS 目录（Komga / Calibre-Web 等），浏览后直接下载入库
      </span>
      <Button size="sm" variant="primary" class="ml-auto" @click="startCreate">添加订阅源</Button>
    </div>

    <Card v-if="editing !== null" class="mb-3" padding="none">
      <div class="border-b border-border px-4 py-3 text-[13px] font-medium text-foreground">
        {{ editing === -1 ? '添加订阅源' : '编辑订阅源' }}
      </div>
      <div class="grid gap-3 px-4 py-3.5 md:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-[12px] text-muted-foreground">名称</span>
          <input
            v-model="form.name"
            type="text"
            class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
            placeholder="我的 Komga"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-muted-foreground">目录地址（OPDS 入口）</span>
          <input
            v-model="form.url"
            type="text"
            class="w-full rounded-md border border-border bg-muted px-3 py-1.5 font-mono text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
            placeholder="http://192.168.1.10:25600/opds/v1.2"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-muted-foreground">用户名（可留空）</span>
          <input
            v-model="form.username"
            type="text"
            class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
          />
        </label>
        <label class="block">
          <span class="mb-1 block text-[12px] text-muted-foreground">
            密码 / API Key<span v-if="editing !== -1" class="ml-1">（留空 = 不修改）</span>
          </span>
          <input
            v-model="form.password"
            type="password"
            class="w-full rounded-md border border-border bg-muted px-3 py-1.5 text-[12.5px] text-foreground outline-none focus:border-ring focus:bg-card"
          />
        </label>
      </div>
      <div class="flex gap-2 border-t border-border px-4 py-3">
        <Button size="sm" variant="primary" :disabled="busy" @click="save">保存</Button>
        <Button size="sm" variant="ghost" @click="editing = null">取消</Button>
      </div>
    </Card>

    <Card padding="none">
      <div v-if="loading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>
      <EmptyState
        v-else-if="!sources.length"
        title="还没有订阅源"
        desc="点右上角「添加订阅源」，填入 OPDS 目录地址（Komga 一般是 http://主机:25600/opds/v1.2）与账号即可。"
      />
      <div v-else class="divide-y divide-border">
        <div
          v-for="s in sources"
          :key="s.id"
          class="flex flex-wrap items-center gap-3 px-4 py-3"
          :class="current?.id === s.id ? 'bg-muted/50' : ''"
        >
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="text-[13px] font-medium text-foreground">{{ s.name }}</span>
              <Badge v-if="s.username">Basic 认证</Badge>
              <Badge v-if="current?.id === s.id" tone="accent">浏览中</Badge>
            </div>
            <div class="mt-0.5 truncate font-mono text-[11.5px] text-muted-foreground">{{ s.url }}</div>
          </div>
          <Button size="sm" :variant="current?.id === s.id ? 'primary' : 'ghost'" @click="open(s)">浏览</Button>
          <Button size="sm" variant="ghost" @click="startEdit(s)">编辑</Button>
          <Button size="sm" variant="ghost" @click="remove(s)">删除</Button>
        </div>
      </div>
    </Card>

    <Card v-if="current" class="mt-4" padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span class="text-[13px] font-medium text-foreground">{{ feed?.title || current.name }}</span>
        <span v-if="feed" class="text-[11.5px] text-muted-foreground">{{ feed.entries.length }} 项</span>
        <div class="ml-auto flex items-center gap-2">
          <Button size="sm" variant="ghost" :disabled="!history.length || busy" @click="back">返回上一层</Button>
          <Button size="sm" variant="ghost" :disabled="busy" @click="browse(feed?.url || '')">刷新</Button>
          <Button
            v-if="feed?.next"
            size="sm"
            :disabled="busy"
            @click="history.push(feed.url), browse(feed.next)"
          >下一页</Button>
        </div>
      </div>

      <div v-if="busy && !feed" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">读取中…</div>
      <EmptyState v-else-if="feed && !feed.entries.length" title="这个目录是空的" desc="换一个源或返回上一层试试。" />
      <div v-else-if="feed" class="divide-y divide-border">
        <div v-for="e in feed.entries" :key="e.href" class="flex items-center gap-3 px-4 py-2.5">
          <div class="min-w-0 flex-1">
            <div class="truncate text-[12.5px] text-foreground">{{ e.title }}</div>
            <div class="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-muted-foreground">
              <span v-if="e.author">{{ e.author }}</span>
              <span v-if="e.series">{{ e.series }}</span>
              <span v-if="e.length">{{ fmtSize(e.length) }}</span>
            </div>
          </div>
          <Button v-if="e.kind === 'nav'" size="sm" variant="ghost" :disabled="busy" @click="enter(e)">进入</Button>
          <Button v-else size="sm" :disabled="busy" @click="download(e)">下载</Button>
        </div>
      </div>
    </Card>

    <Card class="mt-4">
      <div class="text-[12.5px] leading-relaxed text-muted-foreground">
        下载的书<strong>直接落进书库</strong>（<code class="font-mono">OUTPUT_DIR</code>），按
        <RouterLink to="/settings/komga" class="underline">设置的输出布局</RouterLink>
        归位：开了 Komga 布局就进系列目录，否则平铺。扩展名优先取自 feed 的 MIME，
        其次看标题，都没有则按 EPUB 处理。同名文件不会覆盖，会直接报错拦下。
      </div>
    </Card>
  </div>
</template>
