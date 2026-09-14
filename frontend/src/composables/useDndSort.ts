import { ref, type Ref } from 'vue'

/**
 * 原生 HTML5 拖拽排序（不引入 vue-draggable-plus）。
 *
 * 性能约束：`dragover` 只改本地视觉态（dragOverIndex），
 * **不在拖动过程中写 store**；只在 `dragend` / `drop` 时提交一次变更。
 * 这样避免高频状态写入导致的整列表重渲染。
 *
 * 同时提供键盘可达路径（上/下移），与 BookOrbit 的上下箭头一致。
 */
export interface DndSortOptions {
  onCommit: (from: number, to: number) => void
}

export function useDndSort(options: DndSortOptions) {
  const dragIndex: Ref<number | null> = ref(null)
  const dragOverIndex: Ref<number | null> = ref(null)

  function onDragStart(index: number, e: DragEvent): void {
    dragIndex.value = index
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move'
      // Firefox 要求设置数据才会真正触发 drag
      e.dataTransfer.setData('text/plain', String(index))
    }
  }

  function onDragOver(index: number, e: DragEvent): void {
    e.preventDefault()
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
    // 只改本地视觉态，不碰 store
    dragOverIndex.value = index
  }

  function onDrop(index: number): void {
    const from = dragIndex.value
    if (from !== null && from !== index) options.onCommit(from, index)
    reset()
  }

  function onDragEnd(): void {
    reset()
  }

  function reset(): void {
    dragIndex.value = null
    dragOverIndex.value = null
  }

  return { dragIndex, dragOverIndex, onDragStart, onDragOver, onDrop, onDragEnd, reset }
}
