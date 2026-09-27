/**
 * 「恢复阅读位置时该信哪一行进度」（第 63 期 4/6：进度按文件维度）。
 *
 * 三个阅读器（章节流 / PDF / 漫画）都要这一件事，而且**口径必须一致** —— 各写一遍的话，
 * 「多文件的书该从哪继续」迟早在其中一处走样。所以抽在这里，一处定义、三处调用。
 *
 * 规则两步：
 * 1. 先按**本机正在读的那个文件**查；
 * 2. 本文件还没有读点 ⇒ 回落到**书级**（`updated_at` 最新的那行），但**只认
 *    「说的不是别的文件」的回落**。
 *
 * 为什么必须回落：KOReader / Komga 那些写入方**不知道文件**，落的正是书级那行。
 * 不回落的话，一本 EPUB + PDF 的书在 NF 里打开会「明明同步过却从第一章开始」。
 *
 * 为什么回落要挑：书级那行可能是**另一个文件**读出来的 —— 书级 = 最新那行，
 * 用户在 PDF 里读到第 90 页，那个 90 是**页码**；拿它去章节流里找第 90 章会跳到毫不
 * 相干的地方，而且是一个「看起来很正常」的章号。判据是响应里的 `file_rel`：
 * 空串 = 那次写入本来就不认文件（可放心用），等于本文件 = 就是本文件。
 *
 * ⚠️ 判「本文件有没有读点」用的是 **`file_rel == null`**（服务端在查不到那一行时回
 * `null`，见 `server.api_get_progress`），**不是** `locator === 0` —— 第 0 章 / 第 1 页
 * 是合法位置，两者会混。
 *
 * 单文件的书（`fileRel` 为 `undefined`）只有一步：直接查书级，与加这一列之前逐字节相同。
 */
import { api, type ProgressState } from './api'

/** 读进度的入口，默认走真实接口。注入是为了让单测不依赖网络（同 `readingSession` 的 `post`）。 */
export type GetProgress = (id: string, fileRel?: string) => Promise<ProgressState>

export async function progressForFile(
  bookId: string,
  fileRel?: string,
  get: GetProgress = (id, rel) => api.getProgress(id, rel),
): Promise<ProgressState> {
  const mine = await get(bookId, fileRel)
  // 不给 fileRel 时 `mine` 本来就是书级；本文件已有读点则直接就是答案
  if (fileRel === undefined || (mine.file_rel !== null && mine.file_rel !== undefined)) return mine
  const bookLevel = await get(bookId)
  // `!bookLevel.file_rel` 同时覆盖空串（那次写入不认文件）与 `undefined`
  //（旧服务端不返回这个字段，按「不知道文件」处理比按「别的文件」处理安全）
  return !bookLevel.file_rel || bookLevel.file_rel === fileRel ? bookLevel : mine
}
