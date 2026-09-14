import type { Component } from 'vue'

import { WIDGET_META, type WidgetId, type WidgetSize } from '@/data/dashboard'

import LibraryOverviewWidget from './LibraryOverviewWidget.vue'
import ReadingGoalWidget from './ReadingGoalWidget.vue'
import ReadingRhythmWidget from './ReadingRhythmWidget.vue'

/**
 * 部件注册表 —— 整套设计的可扩展性支点。
 *
 * 12 个部件全部登记；`component` 为 null 即本轮未实现，
 * 渲染层跳过、自定义面板置灰标注「待实现」。
 *
 * 扩展方式：下一轮补部件时只需实现组件并把 null 换成组件，
 * 渲染层与设置面板**一行都不用改**。
 */
export interface WidgetDef {
  id: WidgetId
  title: string
  description: string
  size: WidgetSize
  component: Component | null
}

/** 本轮已实现的三个（其余为 null） */
const IMPLEMENTED: Partial<Record<WidgetId, Component>> = {
  'library-overview': LibraryOverviewWidget,
  'reading-goal': ReadingGoalWidget,
  'reading-rhythm': ReadingRhythmWidget,
}

export const WIDGETS: WidgetDef[] = WIDGET_META.map((meta) => ({
  ...meta,
  component: IMPLEMENTED[meta.id] ?? null,
}))

export function widgetById(id: WidgetId): WidgetDef | undefined {
  return WIDGETS.find((w) => w.id === id)
}

/** 该部件是否已实现（自定义面板据此决定是否置灰） */
export function isImplemented(id: WidgetId): boolean {
  return Boolean(widgetById(id)?.component)
}

/**
 * 部件在栅格中占的列数。
 * lg = 占满整行；md = 两列中的一列；sm = 三列中的一列。
 */
export const SIZE_SPAN: Record<WidgetSize, string> = {
  lg: 'col-span-6',
  md: 'col-span-3',
  sm: 'col-span-2',
}
