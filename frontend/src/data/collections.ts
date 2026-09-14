/**
 * 侧栏三组条目 + 详情页辅助数据。
 * 迁移自 v2 app.js：LIBRARIES（66–76）、SMART_SHELVES（79–85）、
 * COLLECTIONS（88–93）、SANTI_VOLUMES（194–223）、BOOK_FILES（226–230）。
 */

export interface NavEntry {
  id: string
  label: string
  icon: string
  count: number
}

/** 书库（侧栏「库」组） */
export const LIBRARIES: NavEntry[] = [
  { id: 'lib-manga', label: '漫画', icon: 'library', count: 55 },
  { id: 'lib-liubei', label: '刘备', icon: 'library', count: 154 },
  { id: 'lib-audio', label: '有声书', icon: 'library', count: 80 },
  { id: 'lib-tools', label: '工具书', icon: 'library', count: 172 },
  { id: 'lib-illus', label: '插图书', icon: 'library', count: 26 },
  { id: 'lib-teach', label: '教学', icon: 'library', count: 17 },
  { id: 'lib-mag', label: '杂志', icon: 'library', count: 3 },
  { id: 'lib-other', label: '其他', icon: 'library', count: 4 },
  { id: 'lib-unsorted', label: '未分类', icon: 'library', count: 12 },
]

/** 智能书架 */
export const SMART_SHELVES: NavEntry[] = [
  { id: 'ss-recent', label: '最近添加', icon: 'sparkle', count: 24 },
  { id: 'ss-unread', label: '未读', icon: 'sparkle', count: 36 },
  { id: 'ss-reading', label: '在读', icon: 'sparkle', count: 5 },
  { id: 'ss-done', label: '已完成', icon: 'sparkle', count: 108 },
  { id: 'ss-high', label: '高分佳作', icon: 'sparkle', count: 42 },
]

/** 收藏夹 */
export const COLLECTIONS: NavEntry[] = [
  { id: 'cl-want', label: '想看', icon: 'star', count: 18 },
  { id: 'cl-read', label: '在读', icon: 'star', count: 7 },
  { id: 'cl-fin', label: '已读完', icon: 'star', count: 96 },
  { id: 'cl-best', label: '年度精选', icon: 'star', count: 12 },
]

export interface Chapter {
  num: number
  title: string
  words: string
  read: boolean
  current?: boolean
}

export interface Volume {
  name: string
  chapters: Chapter[]
}

/** 《三体》结构化卷/章，用于详情页目录（照参考页固定数据） */
export const SANTI_VOLUMES: Volume[] = [
  {
    name: '第一部 · 科学边界',
    chapters: [
      { num: 1, title: '科学边界', words: '4200', read: true },
      { num: 2, title: '台球', words: '3800', read: true },
      { num: 3, title: '射手与农场主', words: '5100', read: true },
      { num: 4, title: '三体、周文王、长夜', words: '4600', read: true },
      { num: 5, title: '叶文洁', words: '5400', read: true },
      { num: 6, title: '宇宙闪烁', words: '3900', read: true },
    ],
  },
  {
    name: '第二部 · 三体游戏',
    chapters: [
      { num: 7, title: '疯狂年代', words: '4800', read: true },
      { num: 8, title: '寂静的春天', words: '4200', read: true },
      { num: 9, title: '红岸之三', words: '5100', read: true },
      { num: 10, title: '红岸之五', words: '4700', read: true },
      { num: 11, title: '红岸之六', words: '5300', read: true },
      { num: 12, title: '三体、牛顿、秦始皇', words: '4400', read: false, current: true },
    ],
  },
  {
    name: '第三部 · 黑暗森林',
    chapters: [
      { num: 13, title: '三体、孔子、墨子', words: '4600', read: false },
      { num: 14, title: '红岸之七', words: '4100', read: false },
      { num: 15, title: '三体、哥白尼、宇宙橄榄球', words: '4900', read: false },
      { num: 16, title: '三体、爱因斯坦、单摆', words: '4300', read: false },
    ],
  },
  {
    name: '第四部 · 黑暗森林（下）',
    chapters: [
      { num: 17, title: '监听员', words: '4700', read: false },
      { num: 18, title: '古筝行动', words: '5200', read: false },
      { num: 19, title: '智子', words: '4500', read: false },
      { num: 20, title: '地球往事', words: '5000', read: false },
    ],
  },
]

export interface BookFile {
  format: string
  size: string
  quality: string
  date: string
  current: boolean
}

/** 详情页文件列表（照参考页固定三条） */
export const BOOK_FILES: BookFile[] = [
  { format: 'EPUB', size: '2.4 MB', quality: '高清', date: '2024-01-15', current: true },
  { format: 'MOBI', size: '1.8 MB', quality: '高清', date: '2024-01-15', current: false },
  { format: 'PDF', size: '8.2 MB', quality: '扫描版', date: '2023-12-20', current: false },
]
