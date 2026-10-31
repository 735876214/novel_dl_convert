import type { PodcastEpisodeLite } from './api'
import { numHit, textHit } from './scopeOps'

/**
 * 播客单集轴的智能范围 / 播放列表（第 186 期）。
 *
 * 规则语义与书级 `smartScope.ts` 相同（空值恒真、all=且 / any=或、操作符走
 * `scopeOps.ts` 的同一份实现），但字段集不同：单集没有作者/系列，只有标题、
 * 所属节目、播放状态、时长、发布天数、下载状态与 explicit。
 *
 * 求值在**前端**：取源是 `GET /api/podcasts/episodes`（全部订阅的单集 lite）。
 * 规则存后端 `podcast_playlists`，与书级 scope 一样只做形状校验。
 */

export type EpisodeScopeField =
  | 'title' | 'podcast' | 'status' | 'duration' | 'published' | 'downloaded' | 'explicit'

export type EpisodeScopeOp = 'contains' | 'not_contains' | 'equals' | 'at_least' | 'at_most'

export interface EpisodeRule {
  field: EpisodeScopeField
  op: EpisodeScopeOp
  value: string
}

export const EPISODE_FIELD_OPS: Record<EpisodeScopeField, EpisodeScopeOp[]> = {
  title: ['contains', 'not_contains', 'equals'],
  podcast: ['contains', 'not_contains', 'equals'],
  status: ['equals'],
  duration: ['at_least', 'at_most'],
  published: ['at_least', 'at_most'],
  downloaded: ['equals'],
  explicit: ['equals'],
}

export const EPISODE_FIELD_LABELS: Record<EpisodeScopeField, string> = {
  title: '单集标题',
  podcast: '所属节目',
  status: '播放状态',
  duration: '时长（分钟）',
  published: '发布天数',
  downloaded: '已下载',
  explicit: 'Explicit',
}

export const EPISODE_OP_LABELS: Record<EpisodeScopeOp, string> = {
  contains: '包含',
  not_contains: '不包含',
  equals: '等于',
  at_least: '至少',
  at_most: '至多',
}

/** 单集状态：已播优先；没有已播时按位置分「进行中 / 未播」。 */
export function episodeStatus(e: PodcastEpisodeLite): 'unplayed' | 'playing' | 'played' {
  if (Number(e.played_at ?? 0) > 0) return 'played'
  return Number(e.position_sec ?? 0) > 0 ? 'playing' : 'unplayed'
}

function ruleHit(e: PodcastEpisodeLite, r: EpisodeRule): boolean {
  const v = String(r.value ?? '').trim()
  if (!v) return true
  switch (r.field) {
    case 'title':
      return textHit(e.title, r.op, v)
    case 'podcast':
      return textHit(e.podcast_title, r.op, v)
    case 'status':
      return textHit(episodeStatus(e), 'equals', v)
    case 'duration':
      return numHit(Number(e.duration_sec ?? 0) / 60, r.op, Number(v))
    case 'published': {
      const t = Number(e.published_at ?? 0)
      if (!t) return false // 没有发布时间的单集不参与「发布了多少天」的比较
      return numHit((Date.now() / 1000 - t) / 86400, r.op, Number(v))
    }
    case 'downloaded':
      return textHit(e.has_local ? 'yes' : 'no', 'equals', v)
    case 'explicit':
      return textHit(e.explicit ? 'yes' : 'no', 'equals', v)
    default:
      return true
  }
}

export function evaluateEpisodeScope(
  episodes: PodcastEpisodeLite[],
  rules: EpisodeRule[],
  match: 'all' | 'any',
): PodcastEpisodeLite[] {
  const rs = (rules || []).filter(Boolean)
  if (!rs.length) return []
  return episodes.filter((e) =>
    match === 'any' ? rs.some((r) => ruleHit(e, r)) : rs.every((r) => ruleHit(e, r)),
  )
}

export function episodeRuleText(r: EpisodeRule): string {
  return `${EPISODE_FIELD_LABELS[r.field] ?? r.field} ${EPISODE_OP_LABELS[r.op] ?? r.op} ${r.value || '…'}`
}

/** 内置「智能播放列表」：不落库，点开即按规则求值（与用户保存的规则同一条求值路径）。 */
export const BUILTIN_PLAYLISTS: { key: string; name: string; match: 'all' | 'any'; rules: EpisodeRule[] }[] = [
  {
    key: 'quick',
    name: '快速听',
    match: 'all',
    rules: [
      { field: 'status', op: 'equals', value: 'unplayed' },
      { field: 'duration', op: 'at_most', value: '30' },
    ],
  },
  {
    key: 'continue',
    name: '继续收听',
    match: 'all',
    rules: [{ field: 'status', op: 'equals', value: 'playing' }],
  },
  {
    key: 'downloaded',
    name: '已下载',
    match: 'all',
    rules: [{ field: 'downloaded', op: 'equals', value: 'yes' }],
  },
  {
    key: 'fresh',
    name: '本周更新',
    match: 'all',
    rules: [
      { field: 'published', op: 'at_most', value: '7' },
      { field: 'status', op: 'equals', value: 'unplayed' },
    ],
  },
]
