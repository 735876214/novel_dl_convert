/**
 * 多值文本输入（题材 / 演播者）的解析 —— **唯一实现**。
 *
 * 单书元数据编辑器与批量元数据编辑都用它：两处各写一份 `split(/[、,，]/)` 时，
 * 只要有一处改了分隔符（例如加上英文逗号），同一段文字在「单本保存」与「批量保存」
 * 就会拆成不同的标签 —— 而这种不一致**不会报错**，只会在书目里长出一堆近义标签。
 */
export function parseTokenList(text: string | null | undefined): string[] {
  return String(text ?? '')
    .split(/[、,，]/)
    .map((s) => s.trim())
    .filter(Boolean)
}
