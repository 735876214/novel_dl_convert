<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import StatTile from '@/components/ui/StatTile.vue'
import { api, type BookFile } from '@/lib/api'
import { fmtBytes } from '@/lib/format'
import { useUiStore } from '@/stores/ui'

/**
 * 文件标签（第 63 期 5/6 重做）：统计条 + 按格式分组 + `THIS FILE` 面板。
 *
 * ⚠️ 这里列的是**这个书目条目自己带的可下载文件**（`book_detail` 的 `files`），
 * 不是书库里同名的其它书 —— 同 stem 的兄弟文件（`三体.epub` 与 `三体.mobi`）在后端
 * 是两个**独立 book_id**（`library._book_id` 取的是含扩展名的 basename），
 * 各自有自己的详情页。多文件进这一列的只有多轨有声书那种目录条目。
 *
 * `THIS FILE` 回答的正是上面那个歧义：这一页说的是**哪一份**（`mainName`），
 * 以及它在磁盘上的位置。
 *
 * ## 路径按访问来源区分（决策 6）
 *
 * **本机 / 局域网**访问给服务器绝对路径 + 复制按钮；**远程**只给库内相对路径。
 * 判据**只在服务端一处**（`server._is_local_request`），前端不猜 —— 这里拿到
 * `local: false` 就是「不给」，而不是「没拉到」。
 *
 * 绝对路径**不在详情响应里**，走单独的 `GET /api/books/{bid}/local-paths`：详情
 * 响应是**与请求者无关**的资源表示，混进来源相关的字段之后，将来任何一层缓存都会
 * 把本机路径回放给远程。那个端点还带 `no-store`。
 *
 * ## 为什么不摆 `ALL PRESENT`
 *
 * 样板顶部那一格来自「扫盘结果 ↔ 库记录」的对账（能查出「记录里有、盘上没了」）。
 * 本项目没有那个数据源：`files` 本身就是**磁盘枚举的结果**，恒全在。
 * 恒真的一格不是信息，是假信息（与「不造假数据」的既有纪律一致，见
 * `BookDetailView.vue` 里删掉写死的「字数：未知」那条注释）。
 */
const props = defineProps<{
  files: BookFile[]
  /** 这本书目自己的库内相对路径（`BookDetail.name`）—— `THIS FILE` 面板用它认人 */
  mainName: string
  /** 这本书目自己的格式（有声书是 AUDIO，且 `files` 为空 —— 成品是个目录） */
  mainFormat: string
  bookId: string
  /** 标签页当前是否可见。**数据等到第一次打开才拉**（见下） */
  active: boolean
}>()

const emit = defineEmits<{ download: [string] }>()

const ui = useUiStore()

const paths = ref<Record<string, string>>({})
const local = ref(false)
/** 已经问过服务端了。复制按钮据此决定露不露脸 —— 没问过就先不摆 */
const probed = ref(false)

/**
 * **每次打开这个标签页都重拉一次**（与 `ReadingLogTab` 同一条理由）：不缓存，
 * 因为这问的是「文件此刻在不在盘上」——缓存住就会拿一个已经搬走的路径去让用户找。
 * 代价是毫秒级的几次 `exists()`。
 */
watch(
  () => [props.active, props.bookId] as const,
  ([active]) => {
    if (!active) return
    void loadPaths()
  },
  { immediate: true },
)

async function loadPaths(): Promise<void> {
  const id = props.bookId
  try {
    const r = await api.bookLocalPaths(id)
    // 竞态：请求在路上时可能已经切到别的书了（同一条路由记录内换书）
    if (id !== props.bookId) return
    // **降级就发生在这一行**：服务端说「不是本机」时，即使响应里带了路径也不采纳。
    // 这**不是第二个判据** —— 判据仍然只有服务端 `_is_local_request` 一处，这里只是
    // 那个判断在下游唯一的落点。若改成在模板里每个消费点各判一次，那才是长出了第二套。
    paths.value = r.local ? r.paths : {}
    local.value = r.local
  } catch {
    // 拉不到就**当没有**：宁可不给路径，也不摆一个可能是旧的路径
    paths.value = {}
    local.value = false
  }
  probed.value = true
}

/** 这本书目对应的那份文件。目录型有声书 `files` 为空 —— 那也是一种「一份」 */
const main = computed(() => ({
  name: props.mainName,
  format: props.mainFormat || '—',
  /** **允许显示**的绝对路径：本机来源才非空（见 `loadPaths`） */
  path: paths.value[props.mainName] ?? '',
}))

const totalSize = computed(() => props.files.reduce((s, f) => s + (f.size || 0), 0))

/**
 * 分组：主文件所在格式排第一（这一页说的是它），其余按「文件数降序 → 格式名字典序」。
 * 顺序**定死**，不依赖 `files` 的原有次序 —— 否则后端换个排序方式这里就跟着抖。
 */
const groups = computed(() => {
  const by = new Map<string, BookFile[]>()
  for (const f of props.files) {
    const k = (f.format || '?').toUpperCase()
    const arr = by.get(k)
    if (arr) arr.push(f)
    else by.set(k, [f])
  }
  const mainKey = (main.value.format || '?').toUpperCase()
  return [...by.entries()]
    .map(([format, items]) => ({
      format,
      items,
      size: items.reduce((s, f) => s + (f.size || 0), 0),
    }))
    .sort((a, b) => {
      if (a.format === mainKey !== (b.format === mainKey)) return a.format === mainKey ? -1 : 1
      if (a.items.length !== b.items.length) return b.items.length - a.items.length
      return a.format.localeCompare(b.format)
    })
})

const formats = computed(() => groups.value.map((g) => g.format))

function fmtDate(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/** 复制哪一条（键是路径本身，不是文件名 —— 两行指向同一个路径时不该一起变「已复制」） */
const copied = ref('')

async function copyPath(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = text
    setTimeout(() => {
      if (copied.value === text) copied.value = ''
    }, 1500)
  } catch {
    ui.toast('复制失败，请手动选中路径')
  }
}

/**
 * 目录型条目 = **有声书**：库里扫到的成品是一个目录（见 `library._row_of`
 * 「音频（单文件或目录）统一成 format="AUDIO"」），所以 `files` 为空。
 * 单文件音频（`三体.mp3`）的 `files` 里有一份，不算这一类。
 */
const isDirBook = computed(() => props.files.length === 0 && (props.mainFormat || '').toUpperCase() === 'AUDIO')
</script>

<template>
  <div>
    <!-- 统计条：三格都只由 `files` 算出来（没有文件就整条不渲染，不摆三个 0） -->
    <div v-if="files.length" class="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <StatTile label="文件" :value="String(files.length)" hint="同名的成品各算一个" />
      <StatTile label="总大小" :value="fmtBytes(totalSize)" />
      <StatTile
        label="格式"
        :value="String(formats.length)"
        :hint="formats.join(' / ')"
      />
    </div>

    <!-- THIS FILE：这一页说的是哪一份、它在磁盘的哪里 -->
    <Card padding="none" :class="files.length ? 'mt-3' : ''">
      <div class="border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">这个条目</h3>
        <p class="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          <template v-if="isDirBook">
            这本书的成品是一个<strong class="text-foreground">目录</strong>（有声书），
            这里给的是那个目录本身的位置；轨道清单在「目录」标签。
          </template>
          <template v-else-if="files.length > 1">
            同名成品有 {{ files.length }} 份，各自是独立的书目条目；这一页说的是下面这一份。
          </template>
          <template v-else>这一页对应的文件。</template>
        </p>
      </div>
      <div class="px-4 py-3">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="grid h-7 w-11 shrink-0 place-items-center rounded-sm bg-muted text-[11px] font-semibold text-foreground"
          >
            {{ main.format }}
          </span>
          <span class="min-w-0 flex-1 truncate text-[12.5px] font-medium text-foreground" :title="main.name">
            {{ main.name }}
          </span>
          <Button
            v-if="main.path"
            size="sm"
            data-test="copy-main-path"
            @click="copyPath(main.path)"
          >
            {{ copied === main.path ? '已复制' : '复制路径' }}
          </Button>
        </div>

        <!--
          `main.path` 已经是「**允许显示**的路径」（远程来源下恒空，见 loadPaths）。
          远程不摆一行「库内相对路径」：`name` 本身就是它，上面那行已经显示出来了，
          同一句话说两遍。
        -->
        <div
          v-if="main.path"
          data-test="main-abs-path"
          class="mt-2 break-all rounded border border-border bg-muted px-2 py-1.5 font-mono text-[11px] text-muted-foreground"
        >
          {{ main.path }}
        </div>
        <!--
          探测过了、本机来源、却一条路径都没拿到：文件在库记录里、在盘上找不到。
          **如实说**，不给一个不存在的路径（给错了比不给更糟 —— 用户照着去找会以为文件丢了）。
        -->
        <p
          v-else-if="probed && local"
          data-test="main-path-missing"
          class="mt-2 text-[11px] text-muted-foreground"
        >
          服务器上没能定位到这个文件。它可能已被移动或删除，刷新书目可重新扫描。
        </p>
      </div>
    </Card>

    <!-- 按格式分组：完整清单（含上面那一份，标「本条目」） -->
    <Card v-if="files.length" padding="none" class="mt-3">
      <div
        v-for="g in groups"
        :key="g.format"
        data-test="format-group"
        class="border-b border-border last:border-b-0"
      >
        <div class="flex items-center gap-2 bg-muted/60 px-4 py-1.5">
          <span class="text-[11px] font-semibold text-foreground">{{ g.format }}</span>
          <span class="text-[11px] text-muted-foreground">{{ g.items.length }} 个</span>
          <span class="ml-auto text-[11px] tabular-nums text-muted-foreground">{{ fmtBytes(g.size) }}</span>
        </div>
        <div
          v-for="f in g.items"
          :key="f.name"
          data-test="file-row"
          class="border-b border-border px-4 py-2.5 last:border-b-0"
        >
          <div class="flex items-center gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="min-w-0 truncate text-[12.5px] font-medium text-foreground" :title="f.name">
                  {{ f.name }}
                </span>
                <Badge v-if="f.name === mainName">本条目</Badge>
              </div>
              <div class="text-[11px] text-muted-foreground">
                {{ fmtBytes(f.size) }} · {{ fmtDate(f.mtime) }}
              </div>
            </div>
            <Button size="sm" @click="emit('download', f.name)">下载</Button>
          </div>
          <!--
            绝对路径只有本机来源才拿得到（决策 6）；远程这一行整个不出现。
            `paths` 在 `loadPaths` 里就已经按来源滤过一遍，这里照常取值即可。
          -->
          <div v-if="paths[f.name]" class="mt-1.5 flex items-center gap-2">
            <span
              class="min-w-0 flex-1 truncate font-mono text-[11px] text-muted-foreground"
              :title="paths[f.name]"
            >{{ paths[f.name] }}</span>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[11px] text-primary hover:underline"
              @click="copyPath(paths[f.name])"
            >
              {{ copied === paths[f.name] ? '已复制' : '复制' }}
            </button>
          </div>
        </div>
      </div>
    </Card>

    <!--
      空态只在「既没有成品文件、也没拿到这本书自己的位置」时出现。
      目录型有声书 `files` 为空、但上面那块给了目录路径 —— 那时不该说「还没有文件」，
      它有一整个目录的轨道（清单在「目录」标签）。
    -->
    <EmptyState
      v-if="!files.length && !main.path"
      class="mt-3"
      icon="file"
      :title="isDirBook ? '目录位置只在服务器本机显示' : '这本书还没有文件'"
      :desc="isDirBook
        ? '有声书的成品是一个目录，这一页只给它在磁盘上的位置。远程访问拿不到服务器路径，轨道清单在「目录」标签。'
        : '转换完成后这里会列出成品文件。'"
    />
  </div>
</template>
