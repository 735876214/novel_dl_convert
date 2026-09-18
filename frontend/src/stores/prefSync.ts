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

export const usePrefSyncStore = defineStore('prefSync', () => {
  const theme = useThemeStore()
  const cover = useCoverPrefsStore()

  const deviceId = ref(deviceIdOf())
  const deviceName = ref(deviceNameOf())
  /** 服务端上的「本设备」记录 */
  const device = ref<PrefDevice | null>(null)
  const profiles = ref<PrefProfile[]>([])
  const devices = ref<PrefDevice[]>([])
  const booted = ref(false)
  const offline = ref(false)
  const busy = ref(false)

  let pushTimer: ReturnType<typeof setTimeout> | null = null
  let pushing = false
  let requeue = false

  /** 收集六块当前值（服务端 payload 的形状） */
  function collect(): PrefsPayload {
    return normalizePayload({
      reader: readReaderPrefs(),
      pdf: readPdfPrefs(),
      comic: readComicPrefs(),
      audio: readAudioPrefs(),
      appearance: { theme: theme.theme, accent: theme.accent, radius: theme.radius },
      cover: { ...cover.prefs },
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
      let remote: PrefDevice | null = null
      try {
        remote = await api.prefDevice(deviceId.value)
      } catch {
        remote = null // 404 = 新设备
      }
      if (remote) {
        device.value = remote
        if (hasPending()) {
          booted.value = true
          await push()
        } else {
          applyPayload(remote.payload)
        }
      } else {
        device.value = await api.prefDeviceUpsert(deviceId.value, {
          name: deviceName.value,
          payload: collect(),
        })
        upsertLocalDeviceRow(device.value)
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

  /** 应用级入口：注册桥回调并启动（幂等） */
  function init(): void {
    onPrefsChanged(onLocalChange)
    void boot()
  }

  return {
    deviceId,
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
