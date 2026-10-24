import { http } from '@kit.NetworkKit';
import { BusinessError } from '@kit.BasicServicesKit';
import { ErrorBody, HealthInfo, LoginResult } from './Models';
import { Session } from './Session';

interface Header {
  'Content-Type': string;
  'Authorization'?: string;
}

/**
 * 唯一出网入口。所有 JSON 请求走这里，页面里不许直接 import http。
 *
 * 错误分三类，页面必须区别对待：
 *   offline=true  → 连不上 NAS（可用本地缓存兜底）
 *   code=401      → 令牌失效（回登录页）
 *   其他          → 服务端明确报错（如实显示 detail）
 */
export class ApiError extends Error {
  code: number = 0;
  offline: boolean = false;

  constructor(code: number, message: string, offline: boolean) {
    super(message);
    this.code = code;
    this.offline = offline;
  }
}

export class Api {
  /** 由登录页 / 设置页写入，来源是 Session.baseUrl() */
  static baseUrl: string = '';
  /** 由登录页写入，来源是 Session.token() */
  static token: string = '';

  static join(path: string): string {
    let b = Api.baseUrl;
    while (b.endsWith('/')) {
      b = b.substring(0, b.length - 1);
    }
    return b + path;
  }

  private static reason(code: number): string {
    if (code === 2300006 || code === 2300007 || code === 2300005) {
      return '连不上服务器，检查是否和 NAS 在同一个 Wi-Fi';
    }
    if (code === 2300028) {
      return '请求超时';
    }
    return '网络错误（' + code + '）';
  }

  private static async send(method: http.RequestMethod, path: string, body: string): Promise<string> {
    if (Api.baseUrl.length === 0) {
      throw new ApiError(-1, '还没有设置服务器地址', false);
    }
    // ArkTS 不允许对 interface 字段做下标赋值（arkts-no-props-by-index），
    // 所以这里用两个完整字面量而不是 `header['Authorization'] = ...`。
    const header: Header = Api.token.length > 0
      ? { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + Api.token }
      : { 'Content-Type': 'application/json' };
    const req = http.createHttp();
    try {
      const res = await req.request(Api.join(path), {
        method: method,
        header: header,
        extraData: body,
        connectTimeout: 5000,
        readTimeout: 20000,
        expectDataType: http.HttpDataType.STRING
      });
      const text = res.result as string;
      if (res.responseCode >= 200 && res.responseCode < 300) {
        return text;
      }
      if (res.responseCode === 401) {
        throw new ApiError(401, '登录已失效，请重新登录', false);
      }
      let detail = '';
      try {
        const eb = JSON.parse(text) as ErrorBody;
        detail = eb.detail === undefined ? '' : eb.detail;
      } catch (e) {
        detail = '';
      }
      const msg = detail.length > 0 ? detail : ('服务端返回 ' + res.responseCode);
      throw new ApiError(res.responseCode, msg, false);
    } catch (e) {
      if (e instanceof ApiError) {
        throw e;
      }
      const be = e as BusinessError;
      throw new ApiError(be.code, Api.reason(be.code), true);
    } finally {
      req.destroy();
    }
  }

  static async get<T>(path: string): Promise<T> {
    const text = await Api.send(http.RequestMethod.GET, path, '');
    return JSON.parse(text) as T;
  }

  static async post<T>(path: string, body: string): Promise<T> {
    const text = await Api.send(http.RequestMethod.POST, path, body);
    return JSON.parse(text) as T;
  }

  static async put<T>(path: string, body: string): Promise<T> {
    const text = await Api.send(http.RequestMethod.PUT, path, body);
    return JSON.parse(text) as T;
  }

  /** GET /health —— 唯一下发版本号的端点，版本门禁只认它 */
  static async health(): Promise<HealthInfo> {
    return Api.get<HealthInfo>('/health');
  }

  /** POST /api/auth/login —— body 字段名是 user / pin（不是 username / password） */
  static async login(user: string, pin: string): Promise<LoginResult> {
    return Api.post<LoginResult>('/api/auth/login', JSON.stringify({ user: user, pin: pin }));
  }

  /** 从 Session 恢复出网配置，每个页面 aboutToAppear 都要先调 */
  static hydrate(): void {
    Api.baseUrl = Session.baseUrl();
    Api.token = Session.token();
  }
}
