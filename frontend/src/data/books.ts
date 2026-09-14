/** 书籍演示数据。迁移自 v2 app.js 的 BOOKS（原第 12–45 行，8 本）。 */

export interface BookSourceRef {
  name: string
  chapters: number
  ok: boolean
}

export interface Book {
  id: number
  title: string
  author: string
  rating: number
  /** 字数文案，如 '446万字' */
  words: string
  pages: number
  year: string
  publisher: string
  isbn: string
  tags: string[]
  /** 封面渐变起色（oklch，对齐 BookOrbit 调色板色相） */
  c1: string
  /** 封面渐变止色 */
  c2: string
  series: string | null
  seriesIndex: number
  /** 进度 % */
  progress: number
  desc: string
  sources: BookSourceRef[]
}

export const BOOKS: Book[] = [
  {
    id: 1,
    title: '诡秘之主',
    author: '爱潜水的乌贼',
    rating: 9.2,
    words: '446万字',
    pages: 1432,
    year: '2018',
    publisher: '起点中文网',
    isbn: '978-7-5321-0001-1',
    tags: ['克苏鲁', '蒸汽朋克', '悬疑'],
    c1: 'oklch(0.42 0.07 275)',
    c2: 'oklch(0.22 0.04 275)',
    series: '诡秘世界',
    seriesIndex: 1,
    progress: 78,
    desc: '蒸汽与机械的浪潮中，谁能触及非凡？历史和黑暗的迷雾里，又是谁在耳语。我从诡秘中醒来，睁眼看见这个世界。蒸汽、机械、枪械、占卜、仪式、魔药……一个充满未知的世界正在展开。',
    sources: [
      { name: '起点中文网', chapters: 1432, ok: true },
      { name: '笔趣阁', chapters: 1432, ok: true },
      { name: '顶点小说', chapters: 1380, ok: false },
    ],
  },
  {
    id: 2,
    title: '三体',
    author: '刘慈欣',
    rating: 9.4,
    words: '88万字',
    pages: 302,
    year: '2008',
    publisher: '重庆出版社',
    isbn: '978-7-5366-9293-0',
    tags: ['硬科幻', '太空歌剧', '雨果奖', '中国科幻', '长篇小说'],
    c1: 'oklch(0.40 0.08 245)',
    c2: 'oklch(0.20 0.04 245)',
    series: '地球往事三部曲',
    seriesIndex: 1,
    progress: 42,
    desc: '文化大革命如火如荼进行的同时，军方探寻外星文明的绝密计划「红岸工程」取得了突破性进展。但在按下发射键的那一刻，历经劫难的叶文洁没有意识到，她彻底改变了人类的命运。地球文明向宇宙发出的第一声啼鸣，以太阳为中心，以光速向宇宙深处飞驰。四光年外，三体文明正苦苦挣扎——三颗无规则运行的太阳主导下的百余次毁灭与重生。而它们，正被迫逃离母星。',
    sources: [
      { name: '微信读书', chapters: 88, ok: true },
      { name: '豆瓣阅读', chapters: 88, ok: true },
    ],
  },
  {
    id: 3,
    title: '长安的荔枝',
    author: '马伯庸',
    rating: 8.9,
    words: '12万字',
    pages: 128,
    year: '2022',
    publisher: '湖南文艺出版社',
    isbn: '978-7-5404-0003-3',
    tags: ['历史', '职场', '短篇'],
    c1: 'oklch(0.43 0.08 28)',
    c2: 'oklch(0.22 0.05 28)',
    series: null,
    seriesIndex: 0,
    progress: 100,
    desc: '大唐天宝十四年，长安城的小吏李善德接到一个任务：要在贵妃诞日之前，从岭南运来新鲜荔枝。荔枝「一日色变，二日香变，三日味变」，山水迢迢五千余里，这是一个不可能完成的任务。',
    sources: [
      { name: '微信读书', chapters: 24, ok: true },
      { name: '起点中文网', chapters: 24, ok: true },
    ],
  },
  {
    id: 4,
    title: '深空彼岸',
    author: '辰东',
    rating: 8.6,
    words: '380万字',
    pages: 1108,
    year: '2021',
    publisher: '起点中文网',
    isbn: '978-7-5321-0004-4',
    tags: ['玄幻', '修仙', '星际'],
    c1: 'oklch(0.40 0.09 292)',
    c2: 'oklch(0.20 0.05 292)',
    series: null,
    seriesIndex: 0,
    progress: 34,
    desc: '浩瀚的宇宙中，一片星系的生灭，也不过是刹那的斑驳流光。仰望星空，总有种结局已注定的感觉。但辰东，一个平凡的青年，却在这宿命的洪流中，看到了不一样的东西。',
    sources: [
      { name: '起点中文网', chapters: 1108, ok: true },
      { name: '得奇小说', chapters: 1090, ok: true },
    ],
  },
  {
    id: 5,
    title: '我们生活在南京',
    author: '天瑞说符',
    rating: 9.0,
    words: '42万字',
    pages: 298,
    year: '2022',
    publisher: '中信出版社',
    isbn: '978-7-5217-0005-5',
    tags: ['科幻', '末世', '温情'],
    c1: 'oklch(0.41 0.06 180)',
    c2: 'oklch(0.21 0.03 180)',
    series: null,
    seriesIndex: 0,
    progress: 0,
    desc: '2019 年，白杨在南京一所大学读大三。2040 年，半夏在末日后的南京独自求生。一台破旧的电波发射机，连接了两个时空。这部小说以极其细腻的笔触，书写了末日中的温情与希望。',
    sources: [{ name: '起点中文网', chapters: 126, ok: true }],
  },
  {
    id: 6,
    title: '大奉打更人',
    author: '卖报小郎君',
    rating: 8.7,
    words: '420万字',
    pages: 1149,
    year: '2020',
    publisher: '起点中文网',
    isbn: '978-7-5321-0006-6',
    tags: ['仙侠', '探案', '轻松'],
    c1: 'oklch(0.42 0.07 56)',
    c2: 'oklch(0.22 0.04 56)',
    series: null,
    seriesIndex: 0,
    progress: 100,
    desc: '这个世界，有儒；有道；有佛；有妖；有术士。警校毕业的许七安幽幽醒来，发现自己身处牢狱之中，三日后流放边陲。他起初只想当一个富家翁，却没想到一步步卷入了朝堂纷争。',
    sources: [
      { name: '起点中文网', chapters: 1149, ok: true },
      { name: '笔趣阁', chapters: 1149, ok: true },
      { name: '铅笔小说', chapters: 1120, ok: true },
    ],
  },
  {
    id: 7,
    title: '球状闪电',
    author: '刘慈欣',
    rating: 8.8,
    words: '24万字',
    pages: 328,
    year: '2005',
    publisher: '四川科学技术出版社',
    isbn: '978-7-5364-0007-7',
    tags: ['硬科幻', '悬疑'],
    c1: 'oklch(0.41 0.07 205)',
    c2: 'oklch(0.21 0.04 205)',
    series: null,
    seriesIndex: 0,
    progress: 65,
    desc: '在某个离奇的雨夜，一颗球状闪电闯进了少年的视野。它的啸叫低沉中透着诡异，像鬼魂的呻吟。这一夜，少年的命运被彻底改变了。他穷其一生，去追寻那个神秘的球状闪电。',
    sources: [{ name: '豆瓣阅读', chapters: 32, ok: true }],
  },
  {
    id: 8,
    title: '凡人修仙传',
    author: '忘语',
    rating: 8.5,
    words: '740万字',
    pages: 2446,
    year: '2008',
    publisher: '起点中文网',
    isbn: '978-7-5321-0008-8',
    tags: ['仙侠', '凡人流', '长篇'],
    c1: 'oklch(0.40 0.07 152)',
    c2: 'oklch(0.21 0.04 152)',
    series: null,
    seriesIndex: 0,
    progress: 12,
    desc: '一个普通山村小子，偶然下进入到当地江湖小门派，成了一名记名弟子。他以这样身份，如何在门派中立足？如何以平庸的资质进入到修仙者的行列？并最终笑傲三界？',
    sources: [
      { name: '起点中文网', chapters: 2446, ok: true },
      { name: '顶点小说', chapters: 2446, ok: false },
    ],
  },
]
