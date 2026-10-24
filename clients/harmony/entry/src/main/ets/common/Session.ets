import { preferences } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';

const STORE_NAME: string = 'nf_session';
export const KEY_BASE: string = 'baseUrl';
export const KEY_TOKEN: string = 'token';
export const KEY_USER: string = 'user';
export const KEY_SKIN: string = 'skin';
export const KEY_DEVICE: string = 'deviceId';

/**
 * 端内唯一的持久化入口。所有键在 init 时一次性读进内存，
 * 之后 get 是同步的 —— 页面渲染不能等 IO。
 */
export class Session {
  private static store: preferences.Preferences | null = null;
  private static cache: Map<string, string> = new Map();

  static async init(ctx: common.Context): Promise<void> {
    Session.store = await preferences.getPreferences(ctx, STORE_NAME);
    const keys: string[] = [KEY_BASE, KEY_TOKEN, KEY_USER, KEY_SKIN, KEY_DEVICE];
    for (const k of keys) {
      const v = await Session.store.get(k, '');
      Session.cache.set(k, v as string);
    }
    if (Session.get(KEY_DEVICE).length === 0) {
      // 设备标识的合法形状由服务端 _DEVICE_ID_RE 钉死：^[A-Za-z0-9_-]{8,64}$
      // UUID 只含十六进制与连字符，加 hm- 前缀后 39 字符，形状天然合规。
      Session.set(KEY_DEVICE, 'hm-' + util.generateRandomUUID(true));
    }
    if (Session.get(KEY_SKIN).length === 0) {
      Session.set(KEY_SKIN, 'paper');
    }
  }

  static get(key: string): string {
    const v = Session.cache.get(key);
    return v === undefined ? '' : v;
  }

  static set(key: string, value: string): void {
    Session.cache.set(key, value);
    const st = Session.store;
    if (st !== null) {
      st.put(key, value).then(() => {
        st.flush();
      });
    }
  }

  static baseUrl(): string {
    return Session.get(KEY_BASE);
  }

  static token(): string {
    return Session.get(KEY_TOKEN);
  }

  static user(): string {
    return Session.get(KEY_USER);
  }

  static deviceId(): string {
    return Session.get(KEY_DEVICE);
  }

  static skin(): string {
    return Session.get(KEY_SKIN);
  }

  static loggedIn(): boolean {
    return Session.token().length > 0 && Session.baseUrl().length > 0;
  }

  /** 退出登录：只清凭证，保留服务器地址 / 设备标识 / 外观主题 */
  static logout(): void {
    Session.set(KEY_TOKEN, '');
    Session.set(KEY_USER, '');
  }
}
