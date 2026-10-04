import { api, apiErrorMessage } from '@/lib/api'

/**
 * 「检查更新」与「用源站整本覆盖本地」的共享实现（第 93 期 E5）。
 *
 * 为什么抽成模块（与第 83 期的 `bookDelete.ts` 同一个理由）：这两件事的**每一句话
 * 都是用户可见的承诺** —— 确认文案、「新增 N 章」、「未自动写入」的原因。书卡 ⋮ 菜单
 * 与详情页的「在线阅读」卡都要调它，抄第二份必然漂移：两处确认文案不一致，
 * 或某处把「什么都没做」报成「已更新」。
 *
 * ## 两条口径写死在文案里（别删）
 *
 * · **默认只追加**：对齐得上才把源站多出来的尾部章节追加到本地末尾，既有章一个都不动
 *   （`manager.update_report` 的保证）⇒ 进度 / 批注不会错位。这是绝大多数时候想要的那件事。
 * · **整本覆盖是另一码事**：按源站那一版**重写**，章节结构可能变 ⇒ 进度按**章号**
 *   重新对齐。所以它必须二次确认，而且要说清代价 —— 不是一句「确定吗？」
 */

/**
 * 整本覆盖的二次确认文案（逐行）。
 *
 * ⚠️ 纯文本（`window.confirm` 不认任何标记）—— 这里**不要**写 `**加粗**` 或反引号，
 * 它们会原样出现在对话框里。第三行给的是**退路**，不是重复的吓唬。
 */
export function overwriteConfirmLines(title: string): string[] {
  return [
    `用源站的内容整本覆盖《${title}》的本地副本？`,
    '',
    '· 本地副本会按「源站那一版」整本重写（不是只追加新章）',
    '· 章节结构可能变 ⇒ 阅读进度按「章号」重新对齐，可能落到别的地方',
    '· 不想冒这个险就先点「检查更新」—— 它会先对齐，对得上才追加新章、对不上一个字都不写',
  ]
}

export interface CheckUpdateResult {
  /** 任务跑完了且没失败 */
  ok: boolean
  /** 给人看的一句话（成功是「新增 N 章」，失败是原因原文） */
  message: string
}

/** 轮询节奏：任务本身是几秒到几十秒，1.2s 一次够快也不会把后端打满 */
const POLL_MS = 1200
/** 上限 ≈ 2 分钟（超时如实说「还在跑」，让用户去任务中心看，而不是假装成功） */
const POLL_MAX = 100

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

/**
 * 起一次「检查更新」并等到有结果 ⇒ 一句话报告。
 *
 * ⚠️ 报告**来自任务行**（`notice` / `error`），不是前端拼的：后端说「源站目录与本地不一致，
 * 未自动写入」时，这里必须原样透出去 —— 那句是用户唯一能知道「为什么没更新」的地方。
 * 所以三档都要有话说：`notice`（干了什么 / 为什么没干）、`error`（失败了）、最后的兜底。
 */
export async function runCheckUpdate(
  id: string,
  opts: { overwrite?: boolean } = {},
): Promise<CheckUpdateResult> {
  let tid = ''
  try {
    const r = await api.checkUpdate(id, !!opts.overwrite)
    tid = r.task_id
  } catch (e) {
    // 400 的 detail 是**指令**（「下载功能未开启」/「先绑一个源」），原文照给
    return { ok: false, message: apiErrorMessage(e, '检查更新失败') }
  }
  for (let i = 0; i < POLL_MAX; i += 1) {
    await sleep(POLL_MS)
    let t
    try {
      t = await api.task(tid)
    } catch {
      continue // 轮询期间的一次失败不该判定整件事失败（下一次就回来了）
    }
    if (t.status === 'done') {
      return { ok: true, message: t.notice || t.result || '已检查，没有新章节' }
    }
    if (t.status === 'failed') {
      return { ok: false, message: t.error || '检查更新失败' }
    }
  }
  return { ok: false, message: '还在跑 —— 进度与结果在「任务中心」看' }
}
