<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, apiErrorMessage, type FileEntry, type WatcherStatus } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useUiStore } from '@/stores/ui'

/**
 * 本地导入（路由名仍是 tools-local）：拖拽上传 / 按路径把文件交给 `pipeline.dispatch`
 * 收进书库，并展示监听目录状态与手动扫描。接真实 /convert、/api/watcher、/api/scan。
 *
 * 第 62 期起 TXT **只入库不转换**（阅读时按需生成派生 EPUB，见 core/txtcache.py），
 * 所以这里不再有「转成繁体」开关 —— 它只对转换链路有意义，而这条链路已经没有了。
 * 页面标题仍是历史命名，路由与键名不动（`features.labels()` 里的标签已改名）。
 *
 * ⚠️ 第 91 期：交互从「转换后把成品下载回浏览器」改成 **投递 → 提示 → 刷新**。
 *
 * 原来的链路是 `api.convertFile` / `api.convertPath`（**blob 变体**）—— 转完把后端返回的
 * 成品文件流 `saveBlob()` 推给用户浏览器存盘。问题是服务端做的其实是同一件事
 * （`pipeline.dispatch` 收进书库），而收书目录页走的是 `convertDrop`（ack，不解析响应体）：
 * **同一个动作，两种客户端语义**。带来的具体怪异有三处：
 *   ① 文件已经进了书库，浏览器里却又多出一份存盘（用户以为「我下到了哪」）；
 *   ② 多选时存盘 N 份、每次覆盖同名下载，浏览器还会拦「是否允许多文件下载」；
 *   ③ 文案写着「逐个入库并下载」，把「入库」和「下载」说成一件事。
 * 现在整条链路与 `BookDockPage.deliverToDock()` 逐字同源：投递 → toast → `refreshInputs()`。
 */
const ui = useUiStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()

/** 0 库文案里的「新建书库」出口：就地弹窗（第 55 期），不再跳设置页 */
function openWizard(): void {
  void wizard.show()
}

const dragging = ref(false)
const busy = ref(false)
const watcher = ref<WatcherStatus | null>(null)
const inputFiles = ref<FileEntry[]>([])
const pathValue = ref('')
const lastResult = ref('')

/**
 * 上传/拖拽允许的扩展名（与后端 `POST /convert` 的允许集一致 = `core/pipeline.EBOOK_EXT`，
 * 含 .txt/.epub/.mobi/.azw3/.pdf/.fb2/.cbz/.cbr 与 `core/audio.AUDIO_EXTS`）。
 * 前端只做**预校验**（后端 400 才报错，但前端应提前给出可读提示，不留「点了没反应」）。
 */
const ALLOWED_EXT = [
  '.txt', '.epub', '.mobi', '.azw3', '.pdf', '.fb2', '.cbz', '.cbr',
  '.m4b', '.mp3', '.m4a', '.opus', '.ogg', '.flac', '.aac', '.wav',
]
const ACCEPT = ALLOWED_EXT.join(',')

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

const watcherRunning = computed(() => Boolean(watcher.value?.running))

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(2)} MB`
}

function refreshWatcher(): void {
  api
    .watcherStatus()
    .then((s) => {
      watcher.value = s
    })
    .catch((e: Error) => ui.toast(e.message))
}

function refreshInputs(): void {
  api
    .files()
    .then((r) => {
      inputFiles.value = r.input ?? []
    })
    .catch((e: Error) => ui.toast(e.message))
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
// 本页没有定时器/轮询，onActivated 反复触发也不会叠加句柄。
onActivated(() => {
  refreshWatcher()
  refreshInputs()
})

/** 0 库守卫（拖拽与按路径两条入口共用一份话术 —— 两套写法迟早在某一处走样） */
function blockedByNoLibrary(): boolean {
  if (!library.hasNoLibraries) return false
  ui.toast('还没有书库：先新建一个书库，投递的文件才有地方归')
  return true
}

async function convertFiles(fileList: FileList | File[]): Promise<void> {
  const files = Array.from(fileList)
  if (!files.length) return

  // 0 库时提前拦下（第 38 期）：`/convert` 会 400 拒收（「还没有书库…」），
  // 与其把文件读进内存再让后端退回来，不如先把话说明白。
  if (blockedByNoLibrary()) return

  // 前端预校验：跳出不支持的格式，给可读提示（不再写死 .txt）
  const allowed = files.filter((f) => ALLOWED_EXT.includes(extOf(f.name)))
  const skipped = files.length - allowed.length
  if (skipped > 0) {
    ui.toast(`已跳过 ${skipped} 个不支持的格式（仅支持 TXT 与电子书/漫画/音频）`)
  }
  if (!allowed.length) return

  busy.value = true
  lastResult.value = ''
  let ok = 0

  for (const file of allowed) {
    try {
      // ⚠️ 走 ack 变体（不解析响应体）：`/convert` 回的是文件流，用 `request()` 会把
      // 字节按 UTF-8 解出 `�` 并报「上传失败」—— 而它其实已经成功了（第 89 期那条老缺陷）。
      await api.convertDrop(file)
      ok += 1
    } catch (err) {
      // 用 `apiErrorMessage` 而不是 `err.message`：后者是后端响应原文（`{"detail":"…"}`），
      // 原样塞进 toast 会把花括号和键名一起露给用户。
      ui.toast(`${file.name}：${apiErrorMessage(err, '投递失败')}`)
    }
  }

  busy.value = false
  lastResult.value = ok ? `已投递 ${ok} / ${allowed.length}` : ''
  if (ok) {
    ui.toast(`已投递 ${ok} 个文件，正在入库`)
    refreshInputs()
  }
}

function onDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files?.length) void convertFiles(e.dataTransfer.files)
}

function onPick(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files?.length) void convertFiles(input.files)
  input.value = ''
}

async function convertByPath(): Promise<void> {
  const p = pathValue.value.trim()
  if (!p) {
    ui.toast('请填写 input 目录下的相对路径')
    return
  }
  if (blockedByNoLibrary()) return
  if (!ALLOWED_EXT.includes(extOf(p))) {
    ui.toast(`不支持的格式：${extOf(p) || '无扩展名'}（仅支持 TXT 与电子书/漫画/音频）`)
    return
  }
  busy.value = true
  try {
    await api.convertPathDrop(p)
    lastResult.value = `已投递 ${p}`
    ui.toast(`已投递 ${p}，正在入库`)
    refreshInputs()
  } catch (err) {
    ui.toast(apiErrorMessage(err, '投递失败'))
  } finally {
    busy.value = false
  }
}

function toggleWatcher(): void {
  const action = watcherRunning.value ? api.watcherStop() : api.watcherStart()
  action
    .then(() => {
      ui.toast(watcherRunning.value ? '已停止监听' : '已开启监听')
      refreshWatcher()
    })
    .catch((e: Error) => ui.toast(e.message))
}

function scan(): void {
  api
    .scanNow()
    .then(() => {
      ui.toast('已触发一轮扫描')
      refreshInputs()
    })
    .catch((e: Error) => ui.toast(e.message))
}
</script>

<template>
  <div>
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- 上传区 -->
      <Card>
        <h3 class="text-[13px] font-semibold text-foreground">拖拽上传（收进书库）</h3>
        <p class="mt-1 mb-2.5 text-[11.5px] text-muted-foreground">
          <template v-if="library.hasNoLibraries">
            还没有书库：收到的东西需要有地方落，现在上传会被拒收。请先
            <button type="button" class="underline" @click="openWizard">新建一个书库</button>。
          </template>
          <template v-else>
            把 TXT 或常见电子书/漫画/音频交给流水线，一律按原样入库（TXT 的目录在阅读时按需生成，见阅读器），或交给下方监听目录自动处理。
          </template>
        </p>

        <label
          class="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors"
          :class="dragging ? 'border-primary bg-[var(--shell-accent-wash)]' : 'border-border hover:border-primary/60'"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <input type="file" :accept="ACCEPT" multiple class="hidden" @change="onPick">
          <span class="grid h-11 w-11 place-items-center rounded-full bg-muted text-muted-foreground">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5">
              <path d="M12 16V4M7.5 8.5L12 4l4.5 4.5M4 20h16" />
            </svg>
          </span>
          <span class="mt-3 text-[13px] font-medium text-foreground">把文件拖到这里，或点击选择</span>
          <span class="mt-1 text-[11.5px] text-muted-foreground">支持 TXT / EPUB / MOBI / PDF / CBZ 等电子书与常见音频；支持多选，逐个投递入库（不会往你浏览器下载任何文件）</span>
        </label>

        <p v-if="lastResult" class="mt-2 text-[11.5px] text-success">{{ lastResult }}</p>
        <p v-if="busy" class="mt-2 text-[11.5px] text-muted-foreground">处理中…</p>
      </Card>

      <!-- 路径转换 + 监听 -->
      <div class="flex min-w-0 flex-col gap-4">
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">按路径入库</h3>
          <div class="flex items-center gap-2">
            <input
              v-model="pathValue"
              type="text"
              placeholder="相对 input 目录，例如 小说/某书.txt 或 漫画.cbz"
              aria-label="待入库文件路径"
              class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
              @keydown.enter="convertByPath"
            >
            <Button variant="primary" :disabled="busy" @click="convertByPath">入库</Button>
          </div>

          <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">input 目录</h3>
          <div v-if="inputFiles.length" class="flex max-h-40 flex-col gap-1 overflow-y-auto">
            <button
              v-for="f in inputFiles"
              :key="f.name"
              type="button"
              class="flex items-center gap-2 rounded-sm px-2 py-1 text-left transition-colors hover:bg-muted"
              @click="pathValue = f.name"
            >
              <span class="min-w-0 flex-1 truncate text-[12px] text-foreground">{{ f.name }}</span>
              <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ fmtSize(f.size) }}</span>
            </button>
          </div>
          <p v-else class="text-[11.5px] text-muted-foreground">目录为空，拖文件进去或放进 input/ 目录。</p>
        </Card>

        <Card>
          <div class="mb-2.5 flex items-center gap-2">
            <h3 class="text-[13px] font-semibold text-foreground">目录监听</h3>
            <Badge :tone="watcherRunning ? 'ok' : 'neutral'" class="ml-auto">
              {{ watcherRunning ? '运行中' : '已停止' }}
            </Badge>
          </div>
          <p class="mb-3 text-[11.5px] text-muted-foreground">
            开启后，放进 input/ 的文件会被自动收进书库（按原样入库，TXT 也不会被转换）。
          </p>
          <div class="flex items-center gap-2">
            <Button :variant="watcherRunning ? 'ghost' : 'primary'" @click="toggleWatcher">
              {{ watcherRunning ? '停止监听' : '开启监听' }}
            </Button>
            <Button @click="scan">立即扫描一轮</Button>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
