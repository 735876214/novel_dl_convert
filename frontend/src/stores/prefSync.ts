import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, type PrefDevice, type PrefProfile } from '@/lib/api'
import { readAudioPrefs, saveAudioPrefs } from '@/lib/audioPrefs'
import { readComicPrefs, saveComicPrefs } from '@/lib/comicPrefs'
import { deviceIdOf, deviceNameOf, setDeviceNameLocally } from '@/lib/deviceInfo'
import { readPdfPrefs, savePdfPrefs } from '@/lib/pdfPrefs'
import { onPrefsChanged, suppressing } from '@/lib/prefsBridge'
import { normalizePayload, payloadEqual, type PrefsPayload } from '@/lib/prefsPayload'
import { readReaderPrefs, saveReaderPrefs } from '@/lib/readerPrefs'
import { useCoverPrefsStore } from '@/stores/coverPrefs'
import { useDisplayPrefsStore } from '@/stores/displayPrefs'
import { useShelfPrefsStore } from '@/stores/shelfPrefs'
import { useThemeStore, type RadiusMode, type ThemeMode } from '@/stores/theme'

/**
 * 偏好同步层：把「阅读偏好 + 外观」与「模式 / 设备」两层概念接起来。
 *
 * 语义（用户拍板）：
 *   · **模式是快照**：应用模式 = 把模式内容**拷贝**到本设备；之后设备各改各的，
 *     改模式本体不影响已拷贝出去的设备。
 *   · **设备各自持有配置**：服务端为每台设备存一条记录；设备配置的改动即时落盘并推送。
 *   · **显式保存**：设备配置与所套用模式不一致时界面提示「已修改」（`dirty`），
 *     用户再决定「保存到当前模式」还是「另存为新模式」。
 *   · **离线降级**：写不上服务端也不阻塞使用（本机缓存照常），恢复后自动重推。
 *
 * localStorage 仍是**首屏与离线的来源**（`index.html` 的防 FOUC 脚本依赖它），
 * 服务端是**真值源**：boot 时按下面的冲突规则决定谁覆盖谁。
 */

const PENDING_KEY = 'nf-prefs-pending'
/** 本机改动合并推送的防抖时长（整包 payload 只有数 KB，整包推比差量简单可靠） */
const PUSH_DEBOUNCE_MS = 800
/** 远端变更检查间隔（第 56 期）：15s 够「感觉到」，又不至于频繁打扰服务端 */
const REMOTE_POLL_MS = 15000

/**
 * 「远端是否比本机新」的判定（第 56 期，**纯函数**，便于单测）。
 *
 * - `noop`：远端没更新（含 1s 容差 —— 时间戳是秒级 float，自身回环不该误判）；
 * - `apply-remote`：本机没有未推送改动 ⇒ 沿用既有「服务端为准」策略静默应用；
 * - `conflict`：本机有未推送改动 ⇒ **只提示、绝不覆盖**（用户显式选保留哪边）。
 */
export type PrefsSyncDecision = 'noop' | 'apply-remote' | 'conflict'

export function prefsSyncDecision(opts: {
  remoteSeen: number
  localSeen: number
  hasPending: boolean
}): PrefsSyncDecision {
  if (!opts.remoteSeen || opts.remoteSeen <= opts.localSeen + 1) return 'noop'
  return opts.hasPending ? 'conflict' : 'apply-remote'
}

export const usePrefSyncStore = defineStore('prefSync', () => {
  const theme = useThemeStore()
  const cover = useCoverPrefsStore()
  const display = useDisplayPrefsStore()
  const shelf = useShelfPrefsStore()

  const deviceId = ref(deviceIdOf())
  const deviceName = ref(deviceNameOf())
  /** 服务端上的「本设备」记录 */
  const device = ref<PrefDevice | null>(null)
  const profiles = ref<PrefProfile[]>([])
  const devices = ref<PrefDevice[]>([])
  const booted = ref(false)
  const offline = ref(false)
  const busy = ref(false)
  /** 第 56 期：远端比本机新、而本机也有未推送改动（只提示，等用户选） */
  const conflict = ref(false)
  /** 第 56 期：刚静默同步过远端偏好（UI 提示一次后自隐） */
  const remoteFresh = ref(false)
  /** 本机「已认账」的远端时间戳（boot / push 后更新），远端是否更新的比较基准 */
  const acceptedSeen = ref(0)
  let remoteTimer: ReturnType<typeof setInterval> | null = null
  let freshTimer: ReturnType<typeof setTimeout> | null = null

  let pushTimer: ReturnType<typeof setTimeout> | null = null
  let pushing = false
  let requeue = false

  /** 收集七块当前值（服务端 payload 的形状） */
  function collect(): PrefsPayload {
    return normalizePayload({
      reader: readReaderPrefs(),
      pdf: readPdfPrefs(),
      comic: readComicPrefs(),
      audio: readAudioPrefs(),
      // 外观块 = 主题/点缀色/圆角 + 布局显示（第 32 期并入，见 prefsPayload 的说明）
      appearance: {
        theme: theme.theme,
        accent: theme.accent,
        radius: theme.radius,
        ...display.prefs,
      },
      cover: { ...cover.prefs },
      // 书架块 = 只挑随账号走的那一项（系列默认折叠，第 43 期）
      shelf: { collapseSeries: shelf.prefs.collapseSeries },
    })
  }

  /** 把远端载荷应用到本机（写缓存 + 外观重挂 class）；期间抑制通知，避免回环推送 */
  function applyPayload(raw: Partial<PrefsPayload> | null | undefined): void {
    const p = normalizePayload(raw)
    suppressing(() => {
      saveReaderPrefs(p.reader)
      savePdfPrefs(p.pdf)
      saveComicPrefs(p.comic)
      saveAudioPrefs(p.audio)
      cover.applyRemote(p.cover)
      theme.applyRemote({
        theme: p.appearance.theme as ThemeMode,
        accent: p.appearance.accent,
        radius: p.appearance.radius as RadiusMode,
      })
      // 同一个 appearance 块喂两个 store：各自只挑自己认识的键（theme 只取三件套，
      // display 只取布局字段），互不污染 —— 两边的 applyRemote 都做了逐键校验
      display.applyRemote(p.appearance)
      // shelf 块同理：只喂可同步键（collapseSeries），本机专属的书架字段不动
      shelf.applyRemote(p.shelf)
    })
  }

  function hasPending(): boolean {
    try {
      return localStorage.getItem(PENDING_KEY) === '1'
    } catch {
      return false
    }
  }

  function markPending(): void {
    try {
      localStorage.setItem(PENDING_KEY, '1')
    } catch {
      /* 隐私模式 */
    }
  }

  function clearPending(): void {
    try {
      localStorage.removeItem(PENDING_KEY)
    } catch {
      /* ignore */
    }
  }

  function upsertLocalDeviceRow(row: PrefDevice): void {
    const i = devices.value.findIndex((d) => d.id === row.id)
    if (i >= 0) devices.value.splice(i, 1, row)
    else devices.value.unshift(row)
  }

  function schedulePush(): void {
    if (pushTimer) clearTimeout(pushTimer)
    pushTimer = setTimeout(() => void push(), PUSH_DEBOUNCE_MS)
  }

  /** 桥回调：本机偏好被改动 */
  function onLocalChange(): void {
    // boot 之前不推：还没拿到服务端状态，推上去可能覆盖掉服务端的更新
    if (!booted.value) return
    markPending()
    schedulePush()
  }

  async function push(): Promise<void> {
    if (pushing) {
      requeue = true
      return
    }
    pushing = true
    try {
      const row = await api.prefDeviceUpsert(deviceId.value, {
        name: deviceName.value,
        payload: collect(),
      })
      device.value = row
      upsertLocalDeviceRow(row)
      acceptedSeen.value = row.last_seen
      clearPending()
      offline.value = false
    } catch {
      offline.value = true
    } finally {
      pushing = false
      if (requeue) {
        requeue = false
        schedulePush()
      }
    }
  }

  /**
   * 启动同步（登录后调用一次；失败不置 booted，便于之后重试）。
   *
   * 冲突规则（两条都必须成立才自洽）：
   *   1. 本机有**未推送的改动** → 本机为准并推上去（否则离线期间改的东西会被静默丢弃）；
   *   2. 否则服务端为准，覆盖本机缓存（换设备/清缓存后回来，配置能跟着回来）；
   *   3. 服务端没有本设备记录 → 用当前本机配置登记（首次上报）。
   */
  async function boot(force = false): Promise<void> {
    if (booted.value && !force) return
    try {
      const [ps, ds] = await Promise.all([api.prefProfiles(), api.prefDevices()])
      profiles.value = ps.items
      devices.value = ds.items
      // 本设备是否已登记，**就在刚拉回来的列表里查**（同一张表、同一个 `_device_out` 序列化），
      // 不再单独 GET 一次单设备：
      //   · 那次 GET 在「新设备」时必然 404 —— 浏览器会把它当作加载失败记进控制台，
      //     而这一层网络日志**任何前端代码都压不掉**，只能靠不发这个请求来消除；
      //   · 语义上它也确实是多余的：`find` 与「取单条」对同一份数据是等价的。
      // 旧的写法是「GET 抛 404 → catch 吞掉 → remote = null」，把「尚未登记」这层
      // 正常契约藏进了异常路径里。
      const remote: PrefDevice | null =
        devices.value.find((d) => d.id === deviceId.value) ?? null
      if (remote) {
        device.value = remote
        acceptedSeen.value = remote.last_seen
        if (hasPending()) {
          booted.value = true
          await push()
        } else {
          applyPayload(remote.payload)
          conflict.value = false
        }
      } else {
        device.value = await api.prefDeviceUpsert(deviceId.value, {
          name: deviceName.value,
          payload: collect(),
        })
        upsertLocalDeviceRow(device.value)
        acceptedSeen.value = device.value.last_seen
        clearPending()
      }
      offline.value = false
      booted.value = true
    } catch {
      offline.value = true
    }
  }

  async function refresh(): Promise<void> {
    try {
      profiles.value = (await api.prefProfiles()).items
      devices.value = (await api.prefDevices()).items
      offline.value = false
    } catch {
      offline.value = true
    }
  }

  /** 当前设备配置 vs 所套用模式：不一致时界面提示「已修改」。未套用模式时恒 false（没有基准） */
  const dirty = computed(() => {
    const pid = device.value?.active_profile_id
    if (!pid) return false
    const prof = profiles.value.find((p) => p.id === pid)
    if (!prof) return false
    return !payloadEqual(normalizePayload(prof.payload), collect())
  })

  const activeProfile = computed(() => {
    const pid = device.value?.active_profile_id
    return pid ? profiles.value.find((p) => p.id === pid) ?? null : null
  })

  /** 应用某个模式到本设备（拷贝语义） */
  async function applyProfile(pid: number): Promise<void> {
    busy.value = true
    try {
      const row = await api.prefDeviceApply(deviceId.value, pid)
      device.value = row
      upsertLocalDeviceRow(row)
      applyPayload(row.payload) // 本机也要立刻跟上（含外观 class）
      clearPending()
      offline.value = false
    } finally {
      busy.value = false
    }
  }

  /** 保存到当前模式：更新模式**本体**；已拷贝出去的其它设备不受影响 */
  async function saveToCurrentProfile(): Promise<void> {
    const prof = activeProfile.value
    if (!prof) return
    busy.value = true
    try {
      const row = await api.prefProfileUpdate(prof.id, { name: prof.name, payload: collect() })
      const i = profiles.value.findIndex((p) => p.id === row.id)
      if (i >= 0) profiles.value.splice(i, 1, row)
      offline.value = false
    } finally {
      busy.value = false
    }
  }

  /** 用本设备当前配置另存为新模式，并把本设备标记为套用它 */
  async function saveAsNewProfile(name: string): Promise<PrefProfile> {
    busy.value = true
    try {
      const prof = await api.prefProfileCreate({ name, payload: collect() })
      profiles.value.unshift(prof)
      const row = await api.prefDeviceUpsert(deviceId.value, {
        name: deviceName.value,
        payload: collect(),
        active_profile_id: prof.id,
      })
      device.value = row
      upsertLocalDeviceRow(row)
      acceptedSeen.value = row.last_seen
      clearPending()
      offline.value = false
      return prof
    } finally {
      busy.value = false
    }
  }

  async function renameProfile(id: number, name: string): Promise<void> {
    const prof = profiles.value.find((p) => p.id === id)
    if (!prof) return
    const row = await api.prefProfileUpdate(id, { name, payload: normalizePayload(prof.payload) })
    const i = profiles.value.findIndex((p) => p.id === id)
    if (i >= 0) profiles.value.splice(i, 1, row)
  }

  /** 删模式：返回被解除引用的设备数（那些设备的配置不变） */
  async function removeProfile(id: number): Promise<number> {
    const r = await api.prefProfileDelete(id)
    profiles.value = profiles.value.filter((p) => p.id !== id)
    // 本设备（及其它设备）的来源标记可能被解除 → 重新拉一遍设备列表
    await refresh()
    device.value = devices.value.find((d) => d.id === deviceId.value) ?? null
    return r.detached_devices
  }

  /** 改名。本设备 → 记到本机并推送；其它设备 → 原 payload 回写（不改它的配置） */
  async function renameDevice(id: string, name: string): Promise<void> {
    const clean = name.trim()
    if (!clean) return
    if (id === deviceId.value) {
      deviceName.value = clean
      setDeviceNameLocally(clean)
      await push()
      return
    }
    const target = devices.value.find((d) => d.id === id)
    if (!target) return
    const row = await api.prefDeviceUpsert(id, {
      name: clean,
      payload: normalizePayload(target.payload),
    })
    upsertLocalDeviceRow(row)
  }

  async function removeDevice(id: string): Promise<void> {
    await api.prefDeviceDelete(id)
    devices.value = devices.value.filter((d) => d.id !== id)
    // 本设备记录被删 → 下次 boot 会用当前配置重新登记
    if (id === deviceId.value) device.value = null
  }

  async function retry(): Promise<void> {
    await push()
    await refresh()
  }

  /**
   * 远端变更检查（第 56 期）：周期性问一次「本设备那行有没有被别人写新」。
   *
   * 与 boot 的两条规则同源，但**多一层保护**：本机有未推送改动时只置 `conflict`
   * （界面给提示），**绝不静默覆盖** —— boot 是启动那一刻的裁决，而这里可能正
   * 有用户在改偏好。只在 boot 完成且页面可见时跑；失败静默（离线照常用本机缓存）。
   */
  async function checkRemote(): Promise<void> {
    if (!booted.value || document.visibilityState !== 'visible') return
    try {
      const row = (await api.prefDevices()).items.find((d) => d.id === deviceId.value) ?? null
      const decision = prefsSyncDecision({
        remoteSeen: row?.last_seen ?? 0,
        localSeen: acceptedSeen.value,
        hasPending: hasPending(),
      })
      if (decision === 'noop') {
        conflict.value = false
        return
      }
      if (decision === 'conflict' || !row) {
        conflict.value = true
        return
      }
      applyPayload(row.payload)
      device.value = row
      acceptedSeen.value = row.last_seen
      conflict.value = false
      remoteFresh.value = true
      if (freshTimer) clearTimeout(freshTimer)
      freshTimer = setTimeout(() => (remoteFresh.value = false), 8000)
    } catch {
      /* 离线 / 服务端不可用：静默，下一轮再试 */
    }
  }

  /** 应用级入口：注册桥回调并启动（幂等） */
  function init(): void {
    onPrefsChanged(onLocalChange)
    void boot()
    // 第 56 期：起远端变更轮询（app 级单例：随外壳存活；visible 才真正发请求）
    if (!remoteTimer) remoteTimer = setInterval(() => void checkRemote(), REMOTE_POLL_MS)
  }

  return {
    deviceId,
    /** 第 56 期：远端与本机都有改动（只提示，等用户选，不自动覆盖） */
    conflict,
    /** 第 56 期：刚静默同步过远端偏好（UI 提示一次后自隐） */
    remoteFresh,
    /** 第 56 期：手动触发一次远端检查（设置页可用） */
    checkRemote,
    deviceName,
    device,
    profiles,
    devices,
    booted,
    offline,
    busy,
    dirty,
    activeProfile,
    collect,
    applyPayload,
    boot,
    refresh,
    applyProfile,
    saveToCurrentProfile,
    saveAsNewProfile,
    renameProfile,
    removeProfile,
    renameDevice,
    removeDevice,
    retry,
    init,
  }
})
