/**
 * 设备身份：本机 id（持久化）+ 设备名（自动推导，可被用户改名覆盖）。
 *
 * id 要满足后端校验 `^[A-Za-z0-9_-]{8,64}$`：`crypto.randomUUID()` 正好合规
 * （36 字符、含连字符）；老浏览器没有 randomUUID 时用随机串兜底。
 * id 只在**本机**持久化 —— 换浏览器/清缓存会被当作新设备，这是刻意的：
 * 服务端不知道「这台机器是谁」，只认这个自报的 id。
 */

const ID_KEY = 'nf-device-id'
const NAME_KEY = 'nf-device-name'

function readLocal(key: string): string {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function writeLocal(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 隐私模式：本次会话仍可用 */
  }
}

function randomId(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch {
    /* 非安全上下文等场景 */
  }
  // 兜底：32 位 base36，长度足够且符合后端字符白名单
  let out = ''
  while (out.length < 24) out += Math.random().toString(36).slice(2)
  return `nf-${out.slice(0, 24)}`
}

/** 本机设备 id（首次调用时生成并持久化） */
export function deviceIdOf(): string {
  let id = readLocal(ID_KEY)
  if (!id) {
    id = randomId()
    writeLocal(ID_KEY, id)
  }
  return id
}

function platformName(): string {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/Android/i.test(ua)) return 'Android'
  if (/(iPhone|iPad|iPod)/i.test(ua)) return 'iOS'
  if (/Mac OS X|Macintosh/i.test(ua)) return 'macOS'
  if (/Windows/i.test(ua)) return 'Windows'
  if (/CrOS/i.test(ua)) return 'ChromeOS'
  if (/Linux/i.test(ua)) return 'Linux'
  return '未知平台'
}

function browserName(): string {
  const ua = typeof navigator === 'undefined' ? '' : navigator.userAgent
  if (/Edg\//.test(ua)) return 'Edge'
  if (/OPR\//.test(ua)) return 'Opera'
  if (/Firefox\//.test(ua)) return 'Firefox'
  if (/Chrome\//.test(ua)) return 'Chrome'
  if (/Safari\//.test(ua)) return 'Safari'
  return '浏览器'
}

/** 自动推导的设备名（如「macOS · Chrome」） */
export function defaultDeviceName(): string {
  return `${platformName()} · ${browserName()}`
}

/** 当前设备名：用户改过就用用户的，否则用自动推导值 */
export function deviceNameOf(): string {
  return readLocal(NAME_KEY) || defaultDeviceName()
}

export function setDeviceNameLocally(name: string): void {
  const n = name.trim()
  if (n) writeLocal(NAME_KEY, n)
  else {
    try {
      localStorage.removeItem(NAME_KEY)
    } catch {
      /* ignore */
    }
  }
}
