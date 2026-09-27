import { ref, type Ref } from 'vue'

/**
 * 书卡 ⋮ 菜单的**唯一**状态源（第 64 期）。
 *
 * ## 为什么是模块单例，而不是每个卡片自己一个 `ref`
 *
 * 一屏可能有 60 张卡，每张卡各自持一个 `open` 布尔 + 各自往 document 上挂一对
 * click / keydown 监听，就是 60 份监听与 60 个真相源 —— 而「菜单同时只该开一个」
 * 这件事在那套写法里**没有任何地方能保证**（要另写互斥逻辑，还得让每张卡都知道
 * 别人开没开）。这里只留一个 `openKey`：开第二个只是把它赋成新的 key，
 * 前一个面板的 `v-if` 自己就为假了 —— 互斥不是规则，是数据结构带来的结果。
 *
 * ## 一个监听器，挂一次，永不摘
 *
 * `install()` 只在**第一次** `toggle` 时挂一次（`installed` 是个模块级布尔，
 * 不是每实例的），此后不再摘除：摘了下次还得再挂，而这条监听的成本是
 * 「一次属性查找」—— 处理器第一句 `if (!openKey.value) return` 就把没开菜单的
 * 绝大多数点击挡掉了。
 *
 * ## 用属性而不是注册表
 *
 * 「点面板内部不关」靠 `closest('[data-book-menu]')`：触发器与面板自己带上这个属性，
 * 谁也不用登记谁。用注册表就得管生命周期（面板 Teleport 到 body，卸载时机与卡片不同步），
 * 而属性是零状态的。仓库里已有按属性查找的先例（`ShelfView` 的 `[data-bucket]`）。
 */

/** 当前打开的面板；`null` = 全都没开。key 用**行 key**（见下） */
const openKey = ref<string | null>(null)

let installed = false

/**
 * 面板与触发器都带这个属性 —— 点它们内部时**不关**（面板里的每一项自己负责关）。
 * 用 `closest` 而不是 `contains`：面板是 Teleport 到 body 的，触发器与面板在 DOM 上
 * 根本不是一棵树，`contains` 判不出来。
 */
const KEEP_OPEN_ATTR = '[data-book-menu]'

function onDocClick(e: MouseEvent): void {
  if (!openKey.value) return
  const t = e.target as Element | null
  // `closest` 只在 Element 上有（点到文本节点时 target 是元素，但 SVG 之类要防一手）
  if (t && typeof t.closest === 'function' && t.closest(KEEP_OPEN_ATTR)) return
  openKey.value = null
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key !== 'Escape' || !openKey.value) return
  openKey.value = null
}

function install(): void {
  if (installed) return
  installed = true
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
}

export interface BookMenuApi {
  openKey: Ref<string | null>
  isOpen(key: string): boolean
  /** 已开 → 关；否则换到该 key（换 key 天然关掉上一个） */
  toggle(key: string): void
  close(): void
}

/**
 * ⚠️ `key` 用**行 key**（`Row.key` / `ListEntry.key` / 表格行的 `key`），不是 `bookId`：
 * 同一本书可以在一屏出现两次（展开的系列里一次、另起一行一次），用 bookId 会让
 * 两个 ⋮ 同时亮着 —— 而且点其中一个，另一个的面板也跟着开。
 */
export function useBookMenu(): BookMenuApi {
  return {
    openKey,
    isOpen(key: string): boolean {
      return openKey.value === key
    },
    toggle(key: string): void {
      install()
      openKey.value = openKey.value === key ? null : key
    },
    close(): void {
      openKey.value = null
    },
  }
}
