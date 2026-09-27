/**
 * 章内字符偏移锚 —— **「算偏移」与「用偏移」必须共用同一套坐标**。
 *
 * ## 为什么需要它
 *
 * 高亮原先只按文本找位置（`ReaderView.wrapQuote`：在章节里搜这段引文，用**第一个**
 * 匹配）。同一章里出现两次的一句话（人名、反复的句子、页眉页脚）就会高亮**错那一处**
 * —— 而且看不出来：高亮确实画上去了，只是画在了别的地方。
 *
 * ## 坐标怎么定义
 *
 * 「章内字符偏移」= **把渲染后的章节内容按文档顺序遍历全部文本节点、首尾相接**之后，
 * 某个字符在这个长串里的下标。区间是**半开**的 `[start, end)`，长度 `end - start`。
 *
 * ⚠️ 这个定义的关键是**遍历顺序**。所以取偏移（`:func:`offsetIn`）与还原区间
 * （`:func:`rangeAt`）都走下面同一个 `textNodes()` —— 两处各写一遍遍历，顺序一旦有
 * 细微差别（比如一个用了 TreeWalker 一个用了递归），偏移就会**整体错位**，
 * 而且错位是静默的：高亮画在了邻近的文字上，看着像「差一点」，实则每条都错。
 *
 * ## 与其他定位方式的关系（三条判据各自的位置）
 *
 * | 方式 | 谁提供 | 本项目能不能**定位** |
 * |---|---|---|
 * | `[start, end)` 字符偏移（本文件） | 本应用阅读器自己算 | **能** —— 坐标就是它自己那套 DOM |
 * | 来源原生锚（KOReader XPointer / Kobo locator） | 设备 | **不能** —— 我们没有它的排版，同一个 `/body/div[3]/p[5]` 落不到同一段文字上 |
 * | 文本搜索（`wrapQuote` 原逻辑） | 引文本身 | 能，但只到「第一个匹配」为止 |
 *
 * 后两者是**回落链**：有偏移且**验得过**就用偏移；否则退回文本搜索；再不行就不画。
 *
 * ## 验不过就不画（这条是安全属性，不是优化）
 *
 * 偏移是**位置**，不是**内容**。书文件换了（重新制版、换了译本、改过章节切分）之后，
 * 老偏移仍然是个合法下标 —— 它会指到一段**完全无关**的文字上。此时直接照偏移画高亮，
 * 等于把用户的批注悄悄挪到别处，**比不画更糟**。所以 `rangeAt` 之后必须核对那一段的
 * 文字是否等于引文；不等就当锚不存在，交给文本搜索兜底。
 */

/** 章节内容根节点下的全部文本节点，**文档顺序**（唯一的遍历口径）。 */
function textNodes(root: HTMLElement): Text[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const out: Text[] = []
  let n: Node | null
  while ((n = walker.nextNode())) out.push(n as Text)
  return out
}

/**
 * 把 `(node, offset)` 换算成章内字符偏移；`node` 不在 `root` 里时返回 **-1**。
 *
 * `node` 是元素节点时（选区端点可以落在元素上，例如整段被选中），`offset` 是**子节点
 * 下标** —— 这里取「该子节点之前的全部文字长度」，即把端点落在那个子节点的**开头**。
 * 这是保守取法：宁可少框住一个字，也不把边界外的文字算进来。
 */
export function offsetIn(root: HTMLElement, node: Node, offset: number): number {
  if (!root.contains(node)) return -1
  let acc = 0
  // 元素端点要记住「这个元素的内容从哪开始、到哪结束」——
  // `offset` 是**子节点下标**，而浏览器实际只会产出两种：0（开头）与 childNodes.length
  // （末尾）。分别对应下面这两个累加器。
  let insideStart = -1
  let insideEnd = -1
  for (const t of textNodes(root)) {
    if (t === node) return acc + Math.min(offset, t.data.length)
    if (node.nodeType === Node.ELEMENT_NODE && node.contains(t)) {
      if (insideStart < 0) insideStart = acc
      insideEnd = acc + t.data.length
    }
    acc += t.data.length
  }
  if (insideStart >= 0) return offset <= 0 ? insideStart : insideEnd
  // 元素端点、且元素里没有文字（空元素）：给章末。**保守**取法 —— 宁可把区间收窄，
  // 也不把范围外的文字算进来。
  // （`node === root` 不走这一支：`root.contains(root)` 为真但 `contains(t)` 对全部 t 成立，
  //  于是走上面那支 —— offset 0 给 0、否则给章末，正是 root 该有的语义。）
  return node.nodeType === Node.ELEMENT_NODE ? acc : -1
}

/**
 * 把选区换算成 `[start, end)`；取不出一条有效区间时返回 `null`。
 *
 * 选区的 `anchorNode`/`focusNode` 取决于用户**从哪头拖**，所以起点终点要按偏移大小
 * 定序，不能想当然认为 anchor 是起点。
 */
export function selectionRange(root: HTMLElement): { start: number; end: number } | null {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null
  const r = sel.getRangeAt(0)
  const a = offsetIn(root, r.startContainer, r.startOffset)
  const b = offsetIn(root, r.endContainer, r.endOffset)
  if (a < 0 || b < 0 || a === b) return null
  return { start: Math.min(a, b), end: Math.max(a, b) }
}

/**
 * 偏移区间 → DOM `Range`；落在区间里的**文字**取出来一并返回。
 *
 * 返回值里的 `text` 是调用方**核对引文**用的（见文件头「验不过就不画」）——
 * 不在这里核对，是因为「相等的定义」属于调用方（阅读器可能想容忍空白差异），
 * 而这个函数的职责只是把坐标翻译成 DOM。
 *
 * 区间跨文本节点时照样返回 Range；但若跨到了元素边界（起点终点不在同一个文本节点、
 * 且中间夹着非文本节点），`Range.surroundContents` 会抛异常 —— 那是调用方的事，
 * 这里如实返回，让它在同一处 catch 里回落。
 */
export function rangeAt(root: HTMLElement, start: number, end: number): { range: Range; text: string } | null {
  if (start < 0 || end <= start) return null
  const nodes = textNodes(root)
  let acc = 0
  let head: Text | null = null
  let headOff = 0
  let tail: Text | null = null
  let tailOff = 0
  for (const t of nodes) {
    const len = t.data.length
    if (head === null && start < acc + len) {
      head = t
      headOff = start - acc
    }
    if (end <= acc + len) {
      tail = t
      tailOff = end - acc
      break
    }
    acc += len
  }
  // 区间末端越过整章（书变短了）：不画，交给文本搜索兜底
  //
  // 这一条**就是**「越界不画」的承载者（实测：把它改成「截断到章末」是等价变异 ——
  // 截断出来的 `tailOff` 必然大于最后一个文本节点的长度，`setEnd` 会自己抛异常，
  // 落进下面那个 catch，照样是 null）。
  if (!head || !tail) return null
  const range = document.createRange()
  // 走到这里 `headOff` / `tailOff` 必定在各自节点的长度之内：它们是「第一个满足
  // `start < acc + len` / `end <= acc + len` 的节点」上的 `start - acc` / `end - acc`，
  // 而 `acc` 单调、`end > start`。所以这个 catch **目前不可达** —— 留着是因为
  // `setStart`/`setEnd` 的越界行为（抛异常 vs 静默调整）在不同实现上有出入，
  // 而这个函数的失败必须表现为「返回 null 交给兜底」，不能是「抛出去打断整章渲染」。
  try {
    range.setStart(head, headOff)
    range.setEnd(tail, tailOff)
  } catch {
    return null
  }
  return { range, text: range.toString() }
}
