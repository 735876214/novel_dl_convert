import type { Component } from 'vue'

import { WIDGET_META, type WidgetId, type WidgetSize } from '@/data/dashboard'

import CurrentlyReadingWidget from './CurrentlyReadingWidget.vue'
import DiversityScoreWidget from './DiversityScoreWidget.vue'
import HighlightOfTheDayWidget from './HighlightOfTheDayWidget.vue'
import LibraryOverviewWidget from './LibraryOverviewWidget.vue'
import LongWaitWidget from './LongWaitWidget.vue'
import MonthlyChallengeWidget from './MonthlyChallengeWidget.vue'
import NeglectedGemsWidget from './NeglectedGemsWidget.vue'
import ReadingDnaWidget from './ReadingDnaWidget.vue'
import ReadingGoalWidget from './ReadingGoalWidget.vue'
import ReadingRhythmWidget from './ReadingRhythmWidget.vue'
import ReadingStreakWidget from './ReadingStreakWidget.vue'
import YearProjectionWidget from './YearProjectionWidget.vue'

/**
 * 部件注册表 —— 整套设计的可扩展性支点。
 *
 * 12 个部件**全部已实现**（数据来自 /api/stats、/api/books、/api/annotations）。
 * 渲染层与设置面板完全由本表驱动：新增部件只需在此登记，页面与面板一行都不用改。
 */
export interface WidgetDef {
  id: WidgetId
  title: string
  description: string
  size: WidgetSize
  component: Component | null
}

const IMPLEMENTED: Partial<Record<WidgetId, Component>> = {
  'library-overview': LibraryOverviewWidget,
  'reading-goal': ReadingGoalWidget,
  'reading-rhythm': ReadingRhythmWidget,
  'currently-reading': CurrentlyReadingWidget,
  'reading-streak': ReadingStreakWidget,
  'reading-dna': ReadingDnaWidget,
  'monthly-challenge': MonthlyChallengeWidget,
  'highlight-of-the-day': HighlightOfTheDayWidget,
  'neglected-gems': NeglectedGemsWidget,
  'diversity-score': DiversityScoreWidget,
  'year-projection': YearProjectionWidget,
  'long-wait': LongWaitWidget,
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
