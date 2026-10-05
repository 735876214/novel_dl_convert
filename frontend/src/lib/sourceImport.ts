/**
 * 「导入书源」的结果 → 一句给用户看的人话（第 94 期）。
 *
 * ## 为什么必须有这个模块
 *
 * 「书源管理 → 导入书源」卡当年只 toast `` `已添加 ${r.added ?? 0} 个书源` ``，
 * 而后端回的 `added` 实际是**名字数组**、被拒时是 `[]` ⇒ 提示渲染成「已添加  个书源」，
 * 屏幕上等于什么都没发生 —— 用户报的「导入书源，项目中没有反应」就是这句提示。
 * 同一个结果在隔壁「书源工具」页（[SourceToolsView.vue]）却按 `counts` 逐档如实回报，
 * 两条路两套口径。
 *
 * 现在**只有本模块**把导入结果翻成人话，两个页面都调它：口径只有一份，
 * 加一个新档位（后端 `ledger.apply` 的 `counts`）也只在这里露面。
 */

/** `ledger.apply` 回的各档计数（键与后端逐字一致，未知键按 0 显示）。 */
export interface ImportCounts {
  new?: number
  update?: number
  duplicate?: number
  conflict?: number
  skipped?: number
  unsupported?: number
  [k: string]: number | undefined
}

/** 逐条失败 / 不可执行的原因。`instead` 是「该怎么做」的建议，可能为空。 */
export interface ImportError {
  name?: string
  error?: string
  instead?: string
}

/** 「快路」返回体（`POST /api/sources`、`/api/sources/upload`）。
 *
 *  ⚠️ **没有逐条差异表**：后端刻意不回（用户的真样本有 1537 条，塞进这个响应体是几 MB，
 *  而这条快路的前端根本不读它）。逐条详情用「书源工具」页的 dry-run。
 */
export interface ImportResult {
  /** ⚠️ 名字**数组**（不是数字）—— 第 94 期修的就是这个类型谎言。 */
  added?: string[]
  errors?: ImportError[]
  counts?: ImportCounts
  /** 识别出的格式标识（`intake.FORMAT_*`）；认不出时后端直接 400，不会走到这里。 */
  format?: string
  /** 上面那个标识的**中文名**，由后端 `sources/formats/base.py:format_label` 下发。
   *
   *  ⚠️ 第 95 期新增。此前前端自抄了一份 `FORMAT_LABELS`，5 个键里已有 3 个与后端的
   *  `display_name` 悄悄发散（「Legado / 阅读书源」vs「Legado / 阅读 App 书源」…）——
   *  界面上的名字只能有一份来源，所以那份表**已删**，名字一律读这里。
   */
  format_label?: string
  origin?: string
}

/**
 * 各档计数 → 一行「新增 X · 更新 Y · …」。
 *
 * ⚠️ **零值也要打出来**：用户看到的若是只有「新增 0」，他无法区分「文件是空的」、
 * 「全是重复的」还是「全是不可执行的」—— 这一行的作用就是回答「为什么没反应」。
 */
export function countsLine(c: ImportCounts = {}): string {
  return (
    `新增 ${c.new ?? 0} · 更新 ${c.update ?? 0} · 重复 ${c.duplicate ?? 0}` +
    ` · 跳过 ${c.skipped ?? 0} · 冲突 ${c.conflict ?? 0} · 不可执行 ${c.unsupported ?? 0}`
  )
}

/**
 * 「有多少条需要人看一眼」——冲突（同站点已有别的源）与不可执行（引擎跑不了）都要算。
 *
 * ⚠️ 冲突**不能**混进「跳过」：跳过是用户自己的选择，冲突是必须由用户决定去处的，
 * 藏起来就等于让两条同站点的源静静地躺在列表里。
 */
export function needsAttention(c: ImportCounts = {}): number {
  return (c.conflict ?? 0) + (c.unsupported ?? 0)
}

/** 完整一句：`导入完成（格式：Legado / 阅读 App 书源）：新增 3 · 更新 0 · …`。
 *
 *  `label` 是后端下发的中文名（`ImportResult.format_label`）；为空时整段括号省掉 ——
 *  前端**不再自己翻译**格式标识（那是 `sources/formats/*` 的 `display_name`）。 */
export function importSummary(counts: ImportCounts = {}, label?: string): string {
  return `导入完成${label ? `（格式：${label}）` : ''}：${countsLine(counts)}`
}

/**
 * 「导入书源」卡的结论（一句话，直接 toast）。
 *
 * 三种情况：① 一切顺利（无冲突、无不可执行、无逐条报错）⇒ 只报计数；
 * ② 有需要看的东西 ⇒ 计数 + 「N 条需要你看一眼（去「书源工具」看原因）」+ 第一条原因原文
 * （原因原文是**后端给的人话**，这里不另写一套解释）；
 * ③ 后端没给计数（极老的响应体）⇒ 退回只报第一条错误，绝不假装成功。
 */
export function importOutcome(r: ImportResult): string {
  const errs = (r.errors ?? []).filter((e) => e.error)
  if (!r.counts) {
    return errs.length ? `导入失败：${errs[0]?.error ?? '规则不合法'}` : '导入失败：响应里没有结果'
  }
  const head = importSummary(r.counts, r.format_label)
  const bad = needsAttention(r.counts)
  if (!bad && !errs.length) return head
  const first = errs[0]?.error ?? ''
  return `${head} —— ${bad || errs.length} 条需要你看一眼（去「书源工具」看原因）${first ? `；例如：${first}` : ''}`
}
