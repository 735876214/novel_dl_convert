/** 书源配置与健康度。迁移自 v2 app.js 的 SOURCES（原第 47–54 行，6 条演示数据）。 */

export interface BookSource {
  name: string
  /** 渐变起色 */
  c1: string
  /** 渐变止色 */
  c2: string
  group: '正版授权' | '公开镜像'
  on: boolean
  /** 成功率 % */
  rate: number
  /** 延迟 ms */
  latency: number
  last: string
}

export const SOURCES: BookSource[] = [
  { name: '起点中文网', c1: '#e8734a', c2: '#a33d1c', group: '正版授权', on: true, rate: 99.2, latency: 142, last: '2 分钟前' },
  { name: '笔趣阁', c1: '#5b8def', c2: '#2c4a99', group: '公开镜像', on: true, rate: 94.6, latency: 352, last: '5 分钟前' },
  { name: '顶点小说', c1: '#8b7cf6', c2: '#4a3d99', group: '公开镜像', on: false, rate: 61.3, latency: 912, last: '1 小时前' },
  { name: '微信读书', c1: '#3fbf7f', c2: '#1c6b47', group: '正版授权', on: true, rate: 97.8, latency: 205, last: '8 分钟前' },
  { name: '豆瓣阅读', c1: '#4ea36e', c2: '#256b40', group: '正版授权', on: true, rate: 96.1, latency: 258, last: '12 分钟前' },
  { name: '得奇小说', c1: '#f0a33c', c2: '#9c6318', group: '公开镜像', on: true, rate: 88.4, latency: 614, last: '34 分钟前' },
]
