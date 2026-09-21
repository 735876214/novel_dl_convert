/**
 * 路径判据：**前端唯一的一处**，向导与编辑弹窗共用。
 *
 * ## 为什么必须抽出来
 *
 * 「成品目录」在两处各有一份预检（`LibraryWizard.vue` / `LibrariesView.vue`），
 * 原本都写死 `raw.startsWith('/')` —— 那是**后端口径的抄错版**。
 * 后端用的是 `pathlib.Path(text).resolve()`（`server.py:_publish_path_allowed`），
 * 它认平台自己的绝对路径；前端只认 POSIX 风格，于是 **Windows 上 `C:\…` 恒被判非法**：
 * 红字常亮、保存按钮恒灰。生产跑在 Linux/Docker 上，所以这个错一直没被看见。
 *
 * 归一化同理：原来比较用 `p.startsWith(`${gp}/`)`，而库根与扫描源目录都是
 * `C:\a\b` 与 `C:/a/b` 混写 ⇒ 重叠检测在 Windows 上**恒为假**（看着有防护，实际没有）。
 *
 * ## 这是「预检」，不是判据本身
 *
 * 权威判据始终在后端。这里只覆盖**纯字符串就能判定**的部分：
 * 不做 `..` 折叠、不解析符号链接 —— 那些交给后端 `resolve()`。
 * 所以前端的漏判不会造成放行错数据，只会让提示来得晚一点（点下去才报 400）。
 */

/** 反斜杠的码点。**不写反斜杠字面量** —— 它在多层转义里会被吃掉，写成码点就没有歧义。 */
const BACKSLASH = String.fromCharCode(92)

/**
 * 是不是绝对路径（与后端 `Path(s).is_absolute()` 同义）。
 *
 * 四种都算：`/…`、`C:\…`、`C:/…`、`\\server\share`。空串不算 ——
 * 调用方各自决定「空」是「没填」还是「非法」（成品目录留空是合法的）。
 */
export function isAbsolutePath(raw: string): boolean {
  const s = raw.trim()
  if (!s) return false
  if (s.startsWith('/')) return true
  if (s.startsWith(BACKSLASH + BACKSLASH)) return true
  // 盘符：第二个字符是冒号、其后紧跟一个分隔符（半截的 `C:` 不算）
  return s.length >= 3 && s[1] === ':' && (s[2] === '/' || s[2] === BACKSLASH)
}

/**
 * 归一化：分隔符统一成 `/`、折叠重复分隔符、去掉尾部分隔符。
 *
 * ⚠️ **不折叠 `..`，也不解析符号链接**。于是 `C:/a/lib/../out` 与 `C:/a/out`
 * 在这里判为不同 —— 这是**故意的**：那种情况后端 `resolve()` 会拦，
 * 前端宁可漏判也不误判（误判会把合法的成品目录挡在外面）。
 */
export function normalizePath(raw: string): string {
  const unified = raw.trim().split(BACKSLASH).join('/').replace(/\/{2,}/g, '/')
  return unified.length > 1 ? unified.replace(/\/+$/, '') : unified
}

/**
 * `a` 与 `b` 是否相交（相等、互为祖先）。
 *
 * 两侧都先归一化 —— 这正是原来漏掉的一步：库根存的是 `C:\a\b`、
 * 用户填的成品目录可能是 `C:/a/b`，不归一化就永远比不中。
 */
export function pathsOverlap(a: string, b: string): boolean {
  const x = normalizePath(a)
  const y = normalizePath(b)
  if (!x || !y) return false
  return x === y || x.startsWith(`${y}/`) || y.startsWith(`${x}/`)
}
