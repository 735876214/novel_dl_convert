export type WhatsNewTag = '新功能' | '优化' | '修复' | '生态'

export interface WhatsNewEntry {
  /** 发布日期（YYYY-MM-DD）；「—」表示不按日期归类（历史总览，不参与「自上次访问」高亮） */
  date: string
  title: string
  /** 分类标签：渲染为低饱和 chip */
  tag: WhatsNewTag
  items: string[]
}

/** 静态更新日志（上游 BookOrbit 的 What's New 同类）。新增功能时在此追加一条即可。 */
export const WHATS_NEW: WhatsNewEntry[] = [
  {
    date: '2026-09-18',
    title: '补齐上游缺口（第 6 期）',
    tag: '优化',
    items: [
      '顶栏新增「外观」快捷浮层：主题 / 点缀色 / 圆角一处搞定',
      '作者页支持按书量 / 姓名排序与「2+ 本」筛选',
      '作者详情支持排序与「打开最近添加」',
      '系列详情标记首册、支持顺序 / 倒序切换',
    ],
  },
  {
    date: '2026-09-17',
    title: '元数据抓取与 Komga 兼容服务端',
    tag: '新功能',
    items: [
      '在线元数据抓取（OpenLibrary / Google Books，先预览再应用）',
      '冒充 Komga 的兼容服务端：第三方 Komga 客户端零改动接入',
    ],
  },
  {
    date: '—',
    title: '基础能力与生态对接',
    tag: '生态',
    items: [
      '书架 / 阅读器（EPUB·PDF·漫画）/ 统计 / 成就',
      'OPDS 目录、KOReader 进度互通、外部服务集成',
      '收书目录、审计日志、任务中心持久化、自定义智能书架',
    ],
  },
]
