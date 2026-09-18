/**
 * 内联 SVG 图标表。
 *
 * 迁移自 v2 app.js 的 ICONS（原第 235–268 行，共 32 个键），逐条照搬 path 数据。
 * 保持内联而非引入图标库：运行时零外部请求，符合 NAS 内网部署要求。
 */
export const ICONS = {
  dash: '<rect x="3" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>',
  shelf: '<path d="M4 4h6v16H4z"/><path d="M13 6.5l4.2-1.2 3.4 14.4-4.2 1.2z"/>',
  task: '<path d="M9.5 6H20M9.5 12H20M9.5 18H20"/><circle cx="4.8" cy="6" r="1.4"/><circle cx="4.8" cy="12" r="1.4"/><circle cx="4.8" cy="18" r="1.4"/>',
  source: '<rect x="3" y="4" width="18" height="6.5" rx="2"/><rect x="3" y="13.5" width="18" height="6.5" rx="2"/><path d="M7 7.2h.01M7 16.8h.01"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/>',
  download: '<path d="M12 3v12M7.5 10.5L12 15l4.5-4.5M4 20h16"/>',
  convert: '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
  book: '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>',
  chev: '<path d="M6 9l6 6 6-6"/>',
  play: '<path d="M6 4l14 8-14 8z"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5h.01"/>',
  user: '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 010 18 15 15 0 010-18z"/>',
  file: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/>',
  note: '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/>',
  more: '<circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/>',
  arrowLeft: '<path d="M19 12H5M12 19l-7-7 7-7"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  bell: '<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>',
  chart: '<path d="M3 20h18"/><rect x="4.5" y="11" width="3.6" height="6.5" rx="1"/><rect x="10.2" y="5" width="3.6" height="12.5" rx="1"/><rect x="15.9" y="14" width="3.6" height="3.5" rx="1"/>',
  wrench: '<path d="M15.5 3.2a5.2 5.2 0 00-4.7 7.4l-7 7a1.9 1.9 0 002.7 2.7l7-7a5.2 5.2 0 007.4-4.7l-3 3-3-.8-.8-3z"/>',
  users: '<path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
  pencil: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z"/>',
  arrowRight: '<path d="M5 12h14M12 5l7 7-7 7"/>',
  library: '<path d="M3 7.2A2.2 2.2 0 015.2 5h13.6A2.2 2.2 0 0121 7.2V9H3z"/><path d="M4.6 9v9.4A1.6 1.6 0 006.2 20h11.6a1.6 1.6 0 001.6-1.6V9"/><path d="M10 13h4"/>',
  star: '<path d="M12 3l2.7 5.4 6 .8-4.3 4.2 1 6-5.4-2.8-5.4 2.8 1-6L3.3 9.2l6-.8z"/>',
  sparkle: '<path d="M11 3l1.7 4.3L17 9l-4.3 1.7L11 15l-1.7-4.3L5 9l4.3-1.7z"/><path d="M18 15l.9 2.1 2.1.9-2.1.9-.9 2.1-.9-2.1-2.1-.9 2.1-.9z"/>',
  logout: '<path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/>',
} as const

export type IconName = keyof typeof ICONS

/** 取图标 path；未知键返回空串（与 v2 的 `ICONS[name] || ''` 行为一致） */
export function iconPath(name: string): string {
  return (ICONS as Record<string, string>)[name] ?? ''
}
