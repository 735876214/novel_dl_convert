<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { api, type SourceStatus, type SourceTestResult } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 书源管理：运行状态（Cookie / 可用性）+ 已注册列表 + 批量粘贴 + 文件上传。
 *
 * 状态来自 /api/sources/status（真实取得：Cookie 落盘情况 + download 配置约束），
 * 原「设置页」中的书源演示数据（成功率 / 延迟）已移除并归并到这里。
 */
const ui = useUiStore()

const sources = ref<SourceStatus[]>([])
const loading = ref(true)
/** 加载失败信息：失败不能退化成「还没有书源」。 */
const error = ref('')
const pasteText = ref('')
const busy = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const stats = computed(() => {
  const total = sources.value.length
  const builtin = sources.value.filter((s) => !s.user).length
  const user = sources.value.filter((s) => s.user).length
  const cookie = sources.value.filter((s) => s.cookie.has).length
  const blocked = sources.value.filter((s) => !s.usable).length
  return { total, builtin, user, cookie, blocked }
})

const downloadEnabled = computed(() => sources.value[0]?.download_enabled ?? false)
const publicOnly = computed(() => sources.value[0]?.public_only ?? true)

function load(): void {
  loading.value = true
  error.value = ''
  api
    .sourcesStatus()
    .then((r) => {
      sources.value = r.items ?? []
    })
    .catch((e: Error) => {
      sources.value = []
      error.value = e.message
    })
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
onActivated(load)

function submitPaste(): void {
  const text = pasteText.value.trim()
  if (!text) {
    ui.toast('请先粘贴书源 JSON')
    return
  }
  busy.value = true
  api
    .addSourcesText(text)
    .then((r) => {
      ui.toast(`已添加 ${r.added ?? 0} 个书源`)
      pasteText.value = ''
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function onFilePick(e: Event): void {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  busy.value = true
  api
    .uploadSourcesFile(file)
    .then((r) => {
      ui.toast(`已从文件添加 ${r.added ?? 0} 个书源`)
      load()
    })
    .catch((err: Error) => ui.toast(err.message))
    .finally(() => {
      busy.value = false
      input.value = ''
    })
}

function remove(name: string): void {
  api
    .deleteSource(name)
    .then(() => {
      ui.toast(`已删除 ${name}`)
      load()
    })
    .catch((e: Error) => ui.toast(e.message))
}

function fmtTime(ts: number | null): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ---------------- 手动添加（表单）+ 逐源连通性自检（第 57 期）----------------
// 表单字段与 `core/sources/rules.py` 的规则 schema 一一对应（不搞第二套命名）。
// 「保存」走既有的 POST /api/sources（同一份校验）；「测试」走 POST /api/sources/test ——
// **只存在于本次请求**，不写盘（写盘的唯一入口是 store.add_rule）。
/** 表单输入框 / 标签的统一样式（模板里字段多，抽出来免得每个都抄一长串类名） */
const INPUT_CLS = 'w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card'
const LABEL_CLS = 'mb-1 block text-[11px] text-muted-foreground'

const showForm = ref(false)
const testQuery = ref('三体')
const testing = ref(false)
/** 试搜结果对应的对象（表单 / 某个已注册源名），用于把结果说清楚 */
const testTarget = ref('')
const testResult = ref<SourceTestResult | null>(null)

const form = ref({
  // 基础
  name: '', display_name: '', domains: '', public: false, concurrency: 8,
  // 搜索
  searchUrl: '', searchMode: 'css' as 'css' | 'regex',
  searchContainer: '', searchPattern: '',
  fTitle: '', fAuthor: '', fUrl: 'a::attr(href)', fCover: 'img::attr(src)',
  // 取书
  bookMode: 'toc' as 'toc' | 'single',
  tocMode: 'css' as 'css' | 'regex', tocContainer: '', tocUrlAttr: 'href', tocPattern: '',
  contentKind: 'text' as 'text' | 'html' | 'regex', contentContainer: '', contentPattern: '',
  // 分章
  chapterMode: 'auto' as 'toc' | 'regex' | 'auto', chapterRegex: '',
})

/** 前端必填校验（与后端 `validate_rule` 同口径，另加「写盘文件名」的字符集检查） */
const formErrors = computed<string[]>(() => {
  const f = form.value
  const errs: string[] = []
  if (!f.name.trim()) errs.push('标识（name）必填')
  else if (!/^[A-Za-z0-9_.-]+$/.test(f.name.trim()))
    errs.push('标识只能用字母 / 数字 / 下划线 / 短横线（它会作为书源文件名）')
  if (!f.domains.trim()) errs.push('域名白名单必填（逗号分隔，如 example.com）')
  if (!f.searchUrl.trim()) errs.push('搜索地址模板必填')
  else if (!f.searchUrl.includes('{title}'))
    errs.push('搜索地址里要有 {title} 占位符，否则每次搜的都是同一个页面')
  if (f.searchMode === 'css' && !f.searchContainer.trim())
    errs.push('CSS 模式需要「结果容器」选择器')
  if (f.searchMode === 'regex' && !f.searchPattern.trim())
    errs.push('正则模式需要「结果正则」（带命名组 title / url）')
  if (f.bookMode === 'toc') {
    if (f.tocMode === 'css' && !f.tocContainer.trim()) errs.push('目录式需要「章节目录容器」选择器')
    if (f.tocMode === 'regex' && !f.tocPattern.trim()) errs.push('目录式需要「章节目录正则」')
  }
  if (f.contentKind === 'regex') {
    if (!f.contentPattern.trim()) errs.push('正则提取正文需要「正文正则」')
  } else if (!f.contentContainer.trim()) {
    errs.push('正文容器必填（单章正文所在元素）')
  }
  if (f.chapterMode === 'regex' && !f.chapterRegex.trim()) errs.push('正则分章需要「章节正则」')
  return errs
})

/** 表单 → 规则 JSON（形状严格对齐 rules.py 的约定） */
function buildRule(): Record<string, unknown> {
  const f = form.value
  const search: Record<string, unknown> = { url: f.searchUrl.trim(), mode: f.searchMode }
  if (f.searchMode === 'css') {
    search.container = f.searchContainer.trim()
    search.fields = {
      title: f.fTitle.trim(),
      author: f.fAuthor.trim(),
      url: f.fUrl.trim() || 'a::attr(href)',
      cover: f.fCover.trim(),
    }
  } else {
    search.pattern = f.searchPattern.trim()
  }
  const content: Record<string, unknown> = f.contentKind === 'regex'
    ? { mode: 'regex', pattern: f.contentPattern.trim() }
    : { mode: 'css', container: f.contentContainer.trim(), [f.contentKind]: true }
  const book: Record<string, unknown> = { mode: f.bookMode, content }
  if (f.bookMode === 'toc') {
    book.toc = f.tocMode === 'css'
      ? { mode: 'css', container: f.tocContainer.trim(), url_attr: f.tocUrlAttr.trim() || 'href' }
      : { mode: 'regex', pattern: f.tocPattern.trim() }
  }
  const chapter: Record<string, unknown> = { mode: f.chapterMode }
  if (f.chapterMode === 'regex') chapter.regex = f.chapterRegex.trim()
  return {
    name: f.name.trim(),
    display_name: f.display_name.trim() || f.name.trim(),
    domains: f.domains.split(/[,，\s]+/).filter(Boolean),
    public: f.public,
    concurrency: Number(f.concurrency) || 8,
    search, book, chapter,
  }
}

function savedOk(r: { added?: number; errors?: Array<{ error?: string }> }, label: string): void {
  if (r.errors?.length) {
    ui.toast(`保存失败：${r.errors[0]?.error ?? '规则不合法'}`)
    return
  }
  ui.toast(`已保存书源 ${label}`)
  load()
}

function saveForm(): void {
  if (formErrors.value.length) {
    ui.toast('请先修完表单里的问题（见下方红字）')
    return
  }
  busy.value = true
  api
    .addSourcesText(JSON.stringify(buildRule()))
    .then((r) => savedOk(r, form.value.name.trim()))
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function _runTest(payload: { rule?: Record<string, unknown>; name?: string }, target: string): void {
  testTarget.value = target
  testResult.value = null
  testing.value = true
  api
    .testSource({ ...payload, query: testQuery.value.trim() || '三体' })
    .then((r) => {
      testResult.value = r
    })
    .catch((e: Error) => {
      testResult.value = { ok: false, errors: [], count: 0, items: [], error: e.message }
    })
    .finally(() => {
      testing.value = false
    })
}

/** 测「表单里正在填的规则」：故意不先跑前端校验 —— 后端会把缺失项逐条说清楚 */
function testForm(): void {
  _runTest({ rule: buildRule() }, form.value.name.trim() || '当前表单')
}

/** 测某个已注册书源（含内置源） */
function testExisting(name: string): void {
  _runTest({ name }, name)
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <!-- 概览 -->
    <div class="grid grid-cols-2 gap-3 md:grid-cols-5">
      <Card v-for="c in [
        { label: '书源总数', value: stats.total, icon: 'source' },
        { label: '内置', value: stats.builtin, icon: 'library' },
        { label: '用户添加', value: stats.user, icon: 'user' },
        { label: '已持久化 Cookie', value: stats.cookie, icon: 'check' },
        { label: '当前不可用', value: stats.blocked, icon: 'alert' },
      ]" :key="c.label">
        <div class="flex items-center gap-2 text-muted-foreground">
          <Icon :name="c.icon" class="h-3.5 w-3.5" />
          <span class="text-[11.5px]">{{ c.label }}</span>
        </div>
        <div class="mt-1.5 text-[20px] leading-none font-semibold text-foreground tabular-nums">
          {{ c.value }}
        </div>
      </Card>
    </div>

    <!-- 手动添加（表单）：第 57 期 —— 三段式填写，保存前可先试搜（不写盘） -->
    <Card padding="none">
      <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">手动添加（表单）</h3>
        <span class="text-[11.5px] text-muted-foreground">
          字段与书源 JSON 规则一一对应；保存前可先「测试」一次
        </span>
        <Button size="sm" class="ml-auto" @click="showForm = !showForm">{{ showForm ? '收起' : '展开' }}</Button>
      </div>

      <!-- 试搜结果：谁测的、结果如何，一眼看清 -->
      <div
        v-if="testResult"
        class="border-b border-border px-4 py-2.5 text-[11.5px]"
        :class="testResult.ok ? 'text-foreground' : 'text-destructive'"
      >
        <div class="font-medium">
          {{ testTarget }}：{{ testResult.ok ? `命中 ${testResult.count} 条` : '未通过' }}
        </div>
        <ul v-if="testResult.errors.length" class="mt-1 list-disc pl-4">
          <li v-for="e in testResult.errors" :key="e">{{ e }}</li>
        </ul>
        <div v-else-if="testResult.error" class="mt-1">{{ testResult.error }}</div>
        <ul v-else-if="testResult.items.length" class="mt-1 space-y-0.5 text-muted-foreground">
          <li v-for="(it, i) in testResult.items" :key="i" class="truncate">
            {{ it.title }}<span v-if="it.author"> · {{ it.author }}</span>
          </li>
        </ul>
        <div v-else class="mt-1 text-muted-foreground">
          能连通但没解析到结果 —— 多半是「结果容器 / 正则」没对上页面结构
        </div>
      </div>

      <div v-if="showForm" class="grid grid-cols-1 gap-4 px-4 py-3.5 lg:grid-cols-3">
        <!-- 基础 -->
        <div>
          <h4 class="mb-2 text-[12px] font-semibold text-foreground">基础</h4>
          <label :class="LABEL_CLS">标识（name，唯一）</label>
          <input v-model="form.name" :class="INPUT_CLS" placeholder="mysite">
          <label :class="LABEL_CLS" class="mt-2">展示名</label>
          <input v-model="form.display_name" :class="INPUT_CLS" placeholder="我的站点">
          <label :class="LABEL_CLS" class="mt-2">域名白名单（逗号分隔）</label>
          <input v-model="form.domains" :class="INPUT_CLS" placeholder="example.com, example.org">
          <div class="mt-2.5 flex items-center gap-4">
            <label class="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <input v-model="form.public" type="checkbox" class="h-3.5 w-3.5 accent-primary">公版 / 合规
            </label>
            <label class="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              并发
              <input
                v-model.number="form.concurrency" type="number" min="1" max="32"
                class="w-16 rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring"
              >
            </label>
          </div>
        </div>

        <!-- 搜索 -->
        <div>
          <h4 class="mb-2 text-[12px] font-semibold text-foreground">搜索</h4>
          <label :class="LABEL_CLS">地址模板（{title} 占位）</label>
          <input v-model="form.searchUrl" :class="INPUT_CLS" placeholder="https://example.com/search?q={title}">
          <div class="mt-2 flex items-center gap-4 text-[11.5px] text-muted-foreground">
            <label class="flex items-center gap-1.5">
              <input v-model="form.searchMode" type="radio" value="css" class="accent-primary">CSS 选择器
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.searchMode" type="radio" value="regex" class="accent-primary">正则
            </label>
          </div>
          <template v-if="form.searchMode === 'css'">
            <label :class="LABEL_CLS" class="mt-2">结果容器</label>
            <input v-model="form.searchContainer" :class="INPUT_CLS" placeholder=".book-item">
            <div class="mt-2 grid grid-cols-2 gap-2">
              <div>
                <label :class="LABEL_CLS">标题选择器</label>
                <input v-model="form.fTitle" :class="INPUT_CLS" placeholder=".name">
              </div>
              <div>
                <label :class="LABEL_CLS">作者选择器</label>
                <input v-model="form.fAuthor" :class="INPUT_CLS" placeholder=".author">
              </div>
              <div>
                <label :class="LABEL_CLS">链接选择器</label>
                <input v-model="form.fUrl" :class="INPUT_CLS" placeholder="a::attr(href)">
              </div>
              <div>
                <label :class="LABEL_CLS">封面选择器</label>
                <input v-model="form.fCover" :class="INPUT_CLS" placeholder="img::attr(src)">
              </div>
            </div>
          </template>
          <template v-else>
            <label :class="LABEL_CLS" class="mt-2">结果正则（命名组 title / url）</label>
            <input
              v-model="form.searchPattern" :class="INPUT_CLS"
              placeholder='&lt;a href="(?P&lt;url&gt;[^"]+)"[^&gt;]*&gt;(?P&lt;title&gt;[^&lt;]+)&lt;/a&gt;'
            >
          </template>
        </div>

        <!-- 取书 + 分章 -->
        <div>
          <h4 class="mb-2 text-[12px] font-semibold text-foreground">取书与分章</h4>
          <div class="flex items-center gap-4 text-[11.5px] text-muted-foreground">
            <label class="flex items-center gap-1.5">
              <input v-model="form.bookMode" type="radio" value="toc" class="accent-primary">目录式
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.bookMode" type="radio" value="single" class="accent-primary">整页式
            </label>
          </div>
          <template v-if="form.bookMode === 'toc'">
            <label :class="LABEL_CLS" class="mt-2">章节目录容器</label>
            <input
              v-if="form.tocMode === 'css'" v-model="form.tocContainer" :class="INPUT_CLS"
              placeholder="#list a"
            >
            <input
              v-else v-model="form.tocPattern" :class="INPUT_CLS"
              placeholder='&lt;a href="(?P&lt;href&gt;[^"]+)"[^&gt;]*&gt;(?P&lt;title&gt;[^&lt;]+)&lt;/a&gt;'
            >
            <div class="mt-2 flex items-center gap-4 text-[11.5px] text-muted-foreground">
              <label class="flex items-center gap-1.5">
                <input v-model="form.tocMode" type="radio" value="css" class="accent-primary">CSS
              </label>
              <label class="flex items-center gap-1.5">
                <input v-model="form.tocMode" type="radio" value="regex" class="accent-primary">正则
              </label>
              <label v-if="form.tocMode === 'css'" class="flex items-center gap-1.5">
                链接属性
                <input
                  v-model="form.tocUrlAttr"
                  class="w-16 rounded-md border border-border bg-muted px-2 py-1 text-[12px] text-foreground outline-none focus:border-ring"
                >
              </label>
            </div>
          </template>
          <div class="mt-2.5 flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
            <label class="flex items-center gap-1.5">
              <input v-model="form.contentKind" type="radio" value="text" class="accent-primary">正文纯文本
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.contentKind" type="radio" value="html" class="accent-primary">保留标签
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.contentKind" type="radio" value="regex" class="accent-primary">正则提取
            </label>
          </div>
          <label :class="LABEL_CLS" class="mt-2">{{ form.contentKind === 'regex' ? '正文正则' : '正文容器' }}</label>
          <input
            v-if="form.contentKind === 'regex'" v-model="form.contentPattern" :class="INPUT_CLS"
            placeholder='&lt;div id="content"&gt;([\s\S]*?)&lt;/div&gt;'
          >
          <input v-else v-model="form.contentContainer" :class="INPUT_CLS" placeholder="#content">
          <label :class="LABEL_CLS" class="mt-2">分章方式</label>
          <div class="flex flex-wrap items-center gap-3 text-[11.5px] text-muted-foreground">
            <label class="flex items-center gap-1.5">
              <input v-model="form.chapterMode" type="radio" value="toc" class="accent-primary">目录
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.chapterMode" type="radio" value="auto" class="accent-primary">自动检测
            </label>
            <label class="flex items-center gap-1.5">
              <input v-model="form.chapterMode" type="radio" value="regex" class="accent-primary">正则
            </label>
          </div>
          <input
            v-if="form.chapterMode === 'regex'" v-model="form.chapterRegex" :class="INPUT_CLS" class="mt-2"
            placeholder="第\s*\d+\s*章"
          >
        </div>
      </div>

      <div v-if="showForm" class="flex flex-wrap items-center gap-2 border-t border-border px-4 py-3">
        <label class="text-[11.5px] text-muted-foreground">测试关键词</label>
        <input
          v-model="testQuery"
          class="w-40 rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12px] text-foreground outline-none focus:border-ring focus:bg-card"
          placeholder="三体"
        >
        <Button :disabled="testing" @click="testForm">{{ testing ? '测试中…' : '测试（不保存）' }}</Button>
        <Button variant="primary" :disabled="busy" @click="saveForm">保存书源</Button>
        <span v-if="formErrors.length" class="text-[11.5px] text-destructive">
          {{ formErrors.length }} 项待修：{{ formErrors[0] }}
        </span>
        <span v-else class="text-[11.5px] text-muted-foreground">表单校验通过</span>
      </div>
    </Card>

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <!-- 导入 -->
      <Card>
        <h3 class="mb-2 text-[13px] font-semibold text-foreground">导入书源</h3>
        <p class="mb-2.5 text-[11.5px] text-muted-foreground">
          支持 JSON 对象 / 数组 / JSONL 三种格式，一次可导入多个书源。
        </p>
        <textarea
          v-model="pasteText"
          rows="7"
          placeholder='{"name": "示例书源", "search": {"url": "..."}}'
          aria-label="粘贴书源 JSON"
          class="w-full resize-y rounded-md border border-border bg-muted px-3 py-2 font-mono text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        />
        <div class="mt-2.5 flex items-center gap-2">
          <Button variant="primary" :disabled="busy" @click="submitPaste">导入</Button>
          <Button :disabled="busy" @click="fileInput?.click()">从文件导入</Button>
          <input ref="fileInput" type="file" accept=".json,.jsonl,.txt" class="hidden" @change="onFilePick">
        </div>
      </Card>

      <!-- 状态列表 -->
      <Card padding="none" class="lg:col-span-2">
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <h3 class="text-[13px] font-semibold text-foreground">书源状态</h3>
          <span class="text-[11.5px] text-muted-foreground">
            共 {{ stats.total }} 个 · 内置 {{ stats.builtin }} 个
          </span>
          <Badge class="ml-auto" :tone="downloadEnabled ? 'ok' : 'warn'">
            {{ downloadEnabled ? '下载已开启' : '下载未开启' }}
          </Badge>
          <Badge v-if="downloadEnabled" :tone="publicOnly ? 'neutral' : 'warn'">
            {{ publicOnly ? '仅公版源' : '全部源放行' }}
          </Badge>
        </div>

        <p v-if="!downloadEnabled" class="border-b border-border bg-muted/60 px-4 py-2 text-[11.5px] text-muted-foreground">
          下载功能当前关闭：在 <code class="font-mono">config.yaml</code> 设 <code class="font-mono">download.enabled: true</code> 后，书源才可用于搜索与下载。
        </p>

        <div v-if="loading" class="px-4 py-8 text-center text-[12.5px] text-muted-foreground">加载中…</div>

        <!-- 加载失败：可重试的错误态（不与「还没有书源」空态混淆） -->
        <div v-else-if="error" class="flex flex-wrap items-center gap-2 px-4 py-6 text-[12.5px] text-destructive">
          <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
          <span>书源加载失败：{{ error }}</span>
          <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
        </div>

        <div v-else-if="sources.length" class="max-h-[30rem] overflow-y-auto">
          <div
            v-for="s in sources"
            :key="s.name"
            class="flex items-start gap-3 border-b border-border/60 px-4 py-3 last:border-b-0"
          >
            <span
              class="mt-1 h-2 w-2 shrink-0 rounded-full"
              :class="s.usable ? 'bg-success' : 'bg-muted-foreground'"
              :title="s.usable ? '当前可用' : s.blocked_reason"
            />

            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-1.5">
                <span class="truncate text-[12.5px] font-medium text-foreground">{{ s.display_name || s.name }}</span>
                <Badge :tone="s.user ? 'accent' : 'neutral'">{{ s.user ? '用户' : '内置' }}</Badge>
                <Badge>{{ s.public ? '公版' : '私有' }}</Badge>
                <Badge v-if="s.cookie.has" tone="ok">已登录</Badge>
              </div>
              <p v-if="s.domains.length" class="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                {{ s.domains.join(' · ') }}
              </p>
              <p v-if="s.cookie.has" class="mt-0.5 text-[11px] text-muted-foreground">
                Cookie 已持久化 · {{ fmtTime(s.cookie.mtime) }}
              </p>
              <p v-if="!s.usable" class="mt-0.5 text-[11px] text-warning">{{ s.blocked_reason }}</p>
            </div>

            <!-- 逐源试搜（第 57 期）：不用真下载就能确认「这个源现在还能不能搜到东西」 -->
            <Button
              size="sm"
              variant="ghost"
              :disabled="testing"
              title="用测试关键词搜一次（不下载、不写盘）"
              @click="testExisting(s.name)"
            >
              测试
            </Button>
            <Button
              v-if="s.user"
              size="sm"
              variant="danger"
              title="删除该书源"
              @click="remove(s.name)"
            >
              删除
            </Button>
            <span v-else class="shrink-0 pt-1 text-[11px] text-muted-foreground">内置不可删</span>
          </div>
        </div>

        <EmptyState v-else icon="source" title="还没有书源" desc="用左侧的批量粘贴或文件导入添加书源。" />
      </Card>
    </div>
  </div>
</template>
