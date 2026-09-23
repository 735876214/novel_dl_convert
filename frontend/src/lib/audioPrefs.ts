/**
 * 有声书播放偏好。
 *
 * 与 `readerPrefs`（eBook）/`pdfPrefs`/`comicPrefs` 分开存：四类阅读器的设置项互不相干，
 * 混在一个键里会让「恢复默认」互相牵连。
 * 单一数据源：localStorage 的 `audio-prefs`（播放器与设置页共读写）。
 */
import { notifyPrefsChanged } from './prefsBridge'

export interface AudioPrefs {
  /** 默认倍速（0.75–2） */
  speed: number
  /** 默认音量 0–1 */
  volume: number
  /** 快退间隔（秒） */
  skipBack: number
  /** 快进间隔（秒） */
  skipForward: number
  /** 睡眠定时默认时长（分钟）；0 = 不启用 */
  sleepMinutes: number
}

export const AUDIO_PREFS_KEY = 'audio-prefs'

export const AUDIO_PREFS_DEFAULT: AudioPrefs = {
  speed: 1,
  volume: 1,
  skipBack: 15,
  skipForward: 30,
  sleepMinutes: 0,
}

/** 倍速档位（对齐上游 0.75x–2x；第 51 期补回 1.75x） */
export const AUDIO_SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2] as const
/** 快退间隔档位（秒） */
export const AUDIO_SKIP_BACKS = [5, 10, 15, 30] as const
/** 快进间隔档位（秒） */
export const AUDIO_SKIP_FORWARDS = [10, 15, 30, 60] as const
/** 睡眠定时档位（分钟）；0 = 关闭 */
export const AUDIO_SLEEPS = [0, 15, 30, 60, 90] as const

export function readAudioPrefs(): AudioPrefs {
  try {
    const raw = localStorage.getItem(AUDIO_PREFS_KEY)
    return raw
      ? { ...AUDIO_PREFS_DEFAULT, ...(JSON.parse(raw) as Partial<AudioPrefs>) }
      : { ...AUDIO_PREFS_DEFAULT }
  } catch {
    return { ...AUDIO_PREFS_DEFAULT }
  }
}

export function saveAudioPrefs(prefs: AudioPrefs): void {
  try {
    localStorage.setItem(AUDIO_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式等场景静默失败 */
  }
  notifyPrefsChanged()
}
