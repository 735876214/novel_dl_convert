import { apiErrorMessage, type BookCard } from '@/lib/api'

/**
 * 「删书」的共享实现（第 83 期，从书卡 ⋮ 菜单抽出来）。
 *
 * 为什么抽：第 83 期给书架行的**快速预览浮层**也加了「删除」。这段流程里每一句
 * 都是**用户可见的承诺**（确认文案、同 stem 兄弟名单、「部分失败」要点名）——
 * 抄第二份必然漂移：两处确认文案不一致，或某处把「部分失败」报成「已删除」。
 * ⇒ 唯一真值源在这里，`BookActionsMenu.vue` 与 `BookPreviewDialog.vue` 都调它。
 *
 * ⚠️ 三条刻意边界：
 *  1. 确认用 `window.confirm`（全站 20 余处惯例，不为这一处新增确认组件）；
 *  2. 同 stem 兄弟名单**只在用户真的点了删除时才拉**（`getDetail`，缓存优先，多数时候零请求）；
 *     拉失败就退化成不带这一行的文案 —— 少一句提醒，比删不掉好；
 *  3. 删除失败**不抛**，返回 `{deleted:false, error}`：调用方据此决定要不要刷新列表。
 */

/** 三份文件的中文名（第 75 期）：toast 里要指名道姓说清是哪一份没删掉 */
export const DELETE_TARGET_LABELS: Record<string, string> = {
  library: '书库里的文件',
  source: '本地的原件',
  copy: '出版副本',
}

/**
 * 同目录、同 stem 的其它格式文件名（取 basename）。
 * `files` 来自详情；拿不到就返回空数组（调用方据此少说一句话）。
 */
export function siblingNamesOf(
  files: readonly { name?: string }[] | undefined,
  mainName: string,
): string[] {
  if (!mainName) return []
  const stemOf = (n: string): string => n.replace(/\.[^./]+$/, '')
  const stem = stemOf(mainName)
  return (files ?? [])
    .map((f) => String(f?.name ?? ''))
    .filter((n) => n && n !== mainName && stemOf(n) === stem)
    .map((n) => n.split('/').pop() || n)
}

/**
 * 删除确认文案（逐行）。
 *
 * 第三行**只在真有同 stem 兄弟时才出** —— 没有兄弟却写「其它格式不会被删除」，
 * 会让人以为还有别的格式存在。
 */
export function deleteConfirmLines(title: string, siblingNames: readonly string[]): string[] {
  const lines = [
    `确定删除《${title}》？`,
    '',
    '· 会移入回收站：书库里的文件、收书目录里的本地原件、出版副本',
    '· 是移入回收站（可恢复，不是真删）',
    '· 阅读进度 / 批注 / 书签 / 评分会保留',
  ]
  if (siblingNames.length) lines.push(`· 同名的其它格式文件（${siblingNames.join('、')}）不会被删除`)
  return lines
}

/**
 * 把三份文件的分项回执拼成一句 toast（第 75 期）。
 *
 * 全成功就说「已移入回收站」；**有任何一份失败必须点名** —— 部分成功却报「已删除」
 * 会让用户以为删干净了，而那份文件其实还躺在原地（静默的部分成功比失败更糟）。
 */
export function deletedToast(
  name: string,
  targets: Record<string, { state?: string; error?: string }> | undefined,
): string {
  const fails = Object.entries(targets ?? {}).filter(([, t]) => t?.state === 'failed')
  if (!fails.length) return `《${name}》已移入回收站`
  const which = fails.map(([k]) => DELETE_TARGET_LABELS[k] ?? k).join('、')
  return `《${name}》部分失败：${which}移不动（${fails[0][1].error || '原因未知'}），其余已进回收站`
}

export interface DeleteBookDeps {
  /** 取详情（列同 stem 兄弟用；缓存优先） */
  getDetail: (id: string) => Promise<{ files?: Array<{ name?: string }> } | null>
  /** 真正删除（`api.deleteBook`） */
  remove: (id: string) => Promise<{ targets?: Record<string, { state?: string; error?: string }> }>
  /** 用户确认；默认 `window.confirm`（测试注入假实现） */
  confirm?: (message: string) => boolean
}

export interface DeleteBookResult {
  /** 真的删了（含「部分失败但已受理」——回执文案里会点名） */
  deleted: boolean
  /** 删成功后的回执 toast 文案 */
  message?: string
  /** 失败原因（已本地化；调用方直接 toast） */
  error?: string
}

/**
 * 确认 + 删除 + 拼回执。**不弹 toast、不刷新列表**（那是调用方的事，两个调用方的
 * toast 习惯不同：菜单走后端错误文案，浮层还要顺手关掉自己）。
 */
export async function confirmAndDeleteBook(
  book: BookCard,
  deps: DeleteBookDeps,
): Promise<DeleteBookResult> {
  const title = book.title || book.name

  let sibs: string[] = []
  try {
    const detail = await deps.getDetail(book.id)
    sibs = siblingNamesOf(detail?.files, book.name)
  } catch {
    sibs = [] // 详情拿不到就不提这一行，不影响删除
  }

  const confirm = deps.confirm ?? ((msg: string) => window.confirm(msg))
  if (!confirm(deleteConfirmLines(title, sibs).join('\n'))) return { deleted: false }

  try {
    const res = await deps.remove(book.id)
    return { deleted: true, message: deletedToast(title, res.targets) }
  } catch (e) {
    return { deleted: false, error: apiErrorMessage(e, '删除失败') }
  }
}
