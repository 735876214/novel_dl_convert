"""Legado（「阅读」App）书源 → 本项目规则：解析 / 能力判定 / 转换 / 登录声明（第 86 期）。

## 这个模块只做四件事，且**全是纯函数、零网络**

1. :func:`parse_sources` 解析输入（数组 / 单对象 / JSONL；坏 JSON 给可读错误）；
2. :func:`analyze` **逐字段判定能力**，产出四档结论与「哪一项、为什么、替代做法」；
3. :func:`convert` 把**可离线确定**的部分转成本项目自有规则（必须能过 ``rules.validate_rule``）；
4. :func:`login_spec` 抽出**该源自己声明的登录需求**，供登录面板按声明渲染；
   另加 :func:`dedup_key` / :func:`rule_hash`（去重与「有更新」判定）与 :func:`js_port`（JS 可移植性）。

## 四档能力结论（``supported``）

- ``yes``：全靠纯字符串 URL / CSS / regex / JSONPath / 模板即可 —— 直接可用；
- ``partial``：规则可转，但**需要 JS 通道**（解密 / 文本替换 / 渲染兜底），或有需要留意的地方
  （个别字段取不出来已略过、源里有「发现页」规则本批忽略）—— 会上台账并显示「需留意」；
- ``no``：用了 **Android 专有桥**（``java.*`` / ``source.*``）或用到了本项目表达不了的形态
  （跨条目拼 URL、`bookSourceUrl` 不是网址）—— 如实标注，**不假装能用**。

## JS 走项目既有 Node 通道，不引 JS 引擎

本项目**已有**解密通道：``core/network.py`` 的 ``run_js`` / ``run_js_async``（模块注释原文
「借助本机 Node 执行站点专用解密脚本（应对字体加密 / 内容混淆）」）+ ``sources/base.py`` 的
``SourceAdapter.decryption_js()`` 钩子 + ``NODE_BIN``（``Dockerfile`` 里是 ``/usr/local/bin/node``）。
所以 Legado 里**只用通用能力**的 JS 是可移植的：约定宿主脚本读全局 ``result``、把明文 ``return``
出去。真正跑不了的只有 Android 专有桥 —— :func:`js_port` 逐条列出缺哪个 API。

⚠️ 部署前提：``NODE_BIN`` 必须存在（本机与容器都要）。缺它时解密会失败 —— 那种「本机能跑、
线上不能跑」的差异是本项目最忌讳的形态，所以 ``analyze`` 把它写进 ``notes`` 提醒。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit

from .model import EXPLORE_KEYS, LEGACY_ALIASES
from . import rules, selspec

#: 四档结论的合法取值
VERDICTS = ("yes", "partial", "no")

#: Legado 里调用 **Android 专有桥** 的痕迹：这些片段服务端无法执行（不是「还没做」，是做不到）。
#: ⚠️ 公开名（不是 `_ANDROID_API_RE`）：`rules.audit_native_rule` 审 JS 字段时也读**这一份**
#: ——「哪些 API 做不到」只许有一处判据。
ANDROID_API_RE = re.compile(
    r"\bjava\.(?:ajax|get|put|post|getElement|getElements|startBrowser|startBrowserAwait|"
    r"toast|longToast|hexDecodeToString|hexDecode|base64Encode|base64Decode|timeFormat|"
    r"androidId|setContent|webView|log)\b"
    r"|\bsource\.(?:getVariable|setVariable|getLoginInfoMap|getKey|bookSourceUrl|loginHeader)\b"
)

#: 字段里出现这些前缀 = 该字段是 JS
_JS_HEAD_RE = re.compile(r"^\s*(?:@js:|<js>|@JS:)", re.I)
#: Legado 正则模式的前缀（`:pattern`）与 JSON 路径的前缀（`$`）
_REGEX_HEAD = ":"

#: 登录字段里出现这些词 ⇒ 视为凭据（界面不回显、导入时标记为必填）
_SECRET_HINT = re.compile(r"密钥|密码|口令|授权|key|token|secret|passwd|password", re.I)

#: 三类书源类型（Legado 的 ``bookSourceType``）：值域以 Legado 源码为准，未知值如实标注
SOURCE_TYPE = {0: "text", 1: "audio", 2: "image", 3: "file"}
SOURCE_TYPE_LABEL = {"text": "文本", "audio": "音频（听书）", "image": "图片（漫画）", "file": "文件"}

#: 阅读 **2.x** 把类型写成**字符串**（实测：``''`` 1368 条 / ``'TEXT'`` 79 / ``'AUDIO'`` 76 /
#: ``'漫画'`` 6 / ``None`` 8）。**逐字**映射到 Legado 的整数枚举；不认识的字符串仍回 ``unknown``。
_SOURCE_TYPE_STR = {"": 0, "TEXT": 0, "AUDIO": 1, "漫画": 2}


# ---------------- 解析 ----------------

def _detect_obj(obj) -> str:
    items = obj if isinstance(obj, list) else [obj]
    for it in items:
        if not isinstance(it, dict):
            continue
        if "bookSourceName" in it or "bookSourceUrl" in it or "ruleSearch" in it:
            return "legado"
        if "name" in it and "domains" in it:
            return "ours"
    return ""


def detect_format(text) -> str:
    """嗅探输入格式 → ``"legado" | "ours" | "jsonl" | ""``（空串 = 认不出）。"""
    if isinstance(text, (list, dict)):
        return _detect_obj(text)
    s = str(text or "").strip()
    if not s:
        return ""
    try:
        return _detect_obj(json.loads(s))
    except Exception:                                     # noqa: BLE001 —— 落到 JSONL 再试
        pass
    lines = [ln for ln in s.splitlines() if ln.strip()]
    for ln in lines[:5]:
        try:
            json.loads(ln)
        except Exception:                                 # noqa: BLE001
            return ""
    return "jsonl" if lines else ""


def parse_sources(text) -> list:
    """解析成条目列表。坏输入抛 ``ValueError``（措辞可直接展示）。"""
    if isinstance(text, (list, dict)):
        obj = text
    else:
        s = str(text or "").strip()
        if not s:
            raise ValueError("内容为空：请粘贴书源 JSON（数组、单个对象，或每行一个 JSON）")
        try:
            obj = json.loads(s)
        except Exception:                                 # noqa: BLE001 —— 再试 JSONL
            obj = []
            for i, ln in enumerate([l for l in s.splitlines() if l.strip()], 1):
                try:
                    obj.append(json.loads(ln))
                except Exception as e:                    # noqa: BLE001
                    raise ValueError(f"第 {i} 行不是合法 JSON：{e}") from None
    items = obj if isinstance(obj, list) else [obj]
    out = [it for it in items if isinstance(it, dict)]
    if not out:
        raise ValueError("没有解析出任何书源条目（顶层既不是对象也不是数组）")
    return out


# ---------------- 去重键与哈希 ----------------

def norm_site(url) -> str:
    """站点归一（去 scheme / www / 尾斜杠、小写）—— 去重判据**只看这一处**。"""
    u = str(url or "").strip().lower()
    u = re.sub(r"^[a-z]+://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def dedup_key(entry: dict) -> str:
    """同一站点 = 同一个 ``dedup_key``（与源名无关：改名不改站点）。

    ⚠️ **不是 http(s) 网址时返回空串**（真实文件 B 的 ``bookSourceUrl`` 就是「大灰狼融合VIP5.0」）：
    拿一个占位串当去重键会让所有「占位式书源」互相判成同一站点 —— 那是**错误的合并**，
    比没有键危险得多。空键由调用方当作「不参与去重」。
    """
    site = str((entry or {}).get("bookSourceUrl") or "").strip()
    if not re.match(r"^https?://", site, re.I):
        return ""
    return norm_site(site)


def rule_hash(entry: dict) -> str:
    """整条源的规范化哈希（键排序，避免键序影响）—— 用于「完全重复」与「有更新」。"""
    canon = json.dumps(entry or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def source_type(entry: dict) -> str:
    """``bookSourceType`` → ``text`` / ``audio`` / ``image`` / ``file`` / ``unknown``（**唯一**判据）。

    两代写法都在这里认：3.x 是整数枚举，2.x 是字符串（``''`` / ``'TEXT'`` / ``'AUDIO'`` / ``'漫画'``）。
    字段缺失与 ``null`` 都按 Legado 的默认值 0（文本）处理 —— 那是 schema 的默认值，不是猜。
    认不出的值仍然回 ``unknown``，由调用方如实标注（**不硬塞进 text**）。
    """
    raw = (entry or {}).get("bookSourceType", 0)
    if raw is None:
        return "text"
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return "text"                                    # 2.x 的空串 = 默认（文本）
        if s not in _SOURCE_TYPE_STR and s.upper() not in _SOURCE_TYPE_STR:
            return "unknown"
        hit = _SOURCE_TYPE_STR[s] if s in _SOURCE_TYPE_STR else _SOURCE_TYPE_STR[s.upper()]
        return SOURCE_TYPE.get(hit, "unknown")
    try:
        return SOURCE_TYPE.get(int(raw), "unknown")
    except (TypeError, ValueError):
        return "unknown"


# ---------------- 方言归一（第 94 期：阅读 2.x → 3.x 键名）----------------

def _set_path(obj: dict, path: str, value):
    """按 ``"ruleSearch.bookList"`` 写进嵌套字典；目标已存在（3.x 键）时**不覆盖**。

    ⚠️ 合并而非替换：`ruleSearchList` / `ruleSearchName` … 会**分别**写进同一个
    `ruleSearch`，逐键新造一个字典会把兄弟键全丢掉（那是 600 条源各少一半字段的静默损失）。
    """
    parts = path.split(".")
    cur = obj
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur.setdefault(parts[-1], value)


def legacy_keys(entry) -> list:
    """这条源里出现的 **2.x 专有键名**（空列表 = 已经是 3.x 形态）。

    ⚠️ 这是「这份文件是哪个方言」的**唯一**判据：`normalize_legacy` 与格式适配器
    （`formats/legado2.py`）/ `intake` 的格式标识都读它，不各写一份。
    """
    ent = entry or {}
    return sorted(k for k in LEGACY_ALIASES if k in ent)


def dialect(entry) -> str:
    """``"legado-2"``（出现 2.x 键名）或 ``"legado-3"``。"""
    return "legado-2" if legacy_keys(entry) else "legado-3"


def normalize_legacy(entry) -> dict:
    """阅读 **2.x** 方言 → 3.x 键名。**纯函数**：不改入参、3.x 输入原样返回。

    ⚠️ 这是「旧方言能不能读」的**唯一**归一实现。`convert` / `analyze` 只认 3.x 键名，
    所以 2.x 必须先过这里 —— 两张映射表（一张在转换里、一张在这里）必然漂移，
    所以 3.x 的键名**一个字都不动**，表在 `model.LEGACY_ALIASES`（只收实测出现过的键）。

    三处**值级**归一（改名表表达不了，逐条写在下面）：`httpUserAgent` → 请求头、
    `searchUrl` 里的**裸词占位符**、`bookSourceType` 的字符串取值（在 `source_type`
    里认，不在这里改）；`serialNumber` 这类 3.x 没有的键**保持原样**
    （`raw_json` 要能无损往返，多一个键不影响执行）。
    """
    ent = dict(entry or {})
    if not legacy_keys(ent):
        return ent
    out: dict = {}
    for k, v in ent.items():
        path = LEGACY_ALIASES.get(k)
        if path:
            _set_path(out, path, v)                          # 3.x 键已存在时不覆盖
        else:
            out[k] = v
    # 2.x 的搜索占位符是**裸词**：实测 1537 条里 1412 条写成 `keyword=searchKey`、
    # 389 条写成 `&page=searchPage`（3.x 才写 `{{key}}` / `{{page}}`）。不做这一步，
    # 转换出来的地址会原样带上 `searchKey` —— 于是「搜什么都搜同一个词」，
    # 而且**一个错都不报**（比抛异常更难发现的一类失效）。
    # ⚠️ 大小写敏感：同一样本里小写 `searchkey=` 是**参数名**（479 条），
    #    驼峰 `searchKey` 才是**值**（`searchKey=` 当参数名出现 0 次）—— 加 re.I 会把参数名也换掉。
    su = out.get("searchUrl")
    if isinstance(su, str) and su:
        out["searchUrl"] = re.sub(r"\bsearchPage\b", "{{page}}",
                                  re.sub(r"\bsearchKey\b", "{{key}}", su))
    # 2.x 的 UA 是**一个字符串**（`httpUserAgent`），3.x 的 `header` 是字典 ⇒ 只在没有
    # 显式 `header` 时补一条 User-Agent（有显式头就以它为准，不合并、不猜）。
    ua = str(ent.get("httpUserAgent") or "").strip()
    if ua and not ent.get("header"):
        out["header"] = {"User-Agent": ua}
    return out


# ---------------- JS 可移植性 ----------------

def _strip_js_wrap(js: str) -> str:
    s = str(js or "").strip()
    if _JS_HEAD_RE.match(s):
        s = re.sub(r"^\s*(?:@js:|@JS:)", "", s)
        s = re.sub(r"^\s*<js>", "", s, flags=re.I)
        s = re.sub(r"</js>\s*$", "", s, flags=re.I)
    return s.strip()


def js_port(js: str) -> dict:
    """把 Legado 的 JS 片段移植成**宿主脚本**：``{ok, script, missing}``。

    宿主约定（与 ``network.run_js`` 对齐）：脚本读全局 ``result``，把明文 ``return`` 出去。
    只用通用能力（字符串 / 正则 / JSON / base64 / 简单取值）⇒ 可直接移植；
    出现 Android 专有桥 ⇒ ``ok=False`` 并把每个缺失 API 列进 ``missing``（不假装能跑）。
    """
    src = _strip_js_wrap(js)
    if not src:
        return {"ok": False, "script": "", "missing": ["（空脚本）"]}
    missing = sorted({m.group(0) for m in ANDROID_API_RE.finditer(src)})
    if missing:
        return {"ok": False, "script": "", "missing": missing}
    return {"ok": True, "script": src, "missing": []}


# ---------------- 登录声明 ----------------

def _login_open_url(entry: dict) -> str:
    """从 ``loginUrl`` 里取出「该去哪个地址完成验证」；取不到给空串。"""
    lu = str((entry or {}).get("loginUrl") or "").strip()
    if not lu:
        return ""
    if re.match(r"^https?://", lu, re.I):
        return lu
    base = str((entry or {}).get("bookSourceUrl") or "")
    m = re.search(r"startBrowserAwait\(\s*source\.bookSourceUrl\s*\+\s*['\"]([^'\"]+)['\"]", lu)
    if m and re.match(r"^https?://", base, re.I):
        return urljoin(base if base.endswith("/") else base + "/", m.group(1).lstrip("/"))
    m = re.search(r"startBrowserAwait\(\s*['\"](https?://[^'\"]+)['\"]", lu)
    return m.group(1) if m else ""


def _var_key(label: str, idx: int) -> str:
    """登录字段 → 变量键：有意义的英文/数字就直接用，否则用位置兜底（中文键也可，但不做拼音）。"""
    s = re.sub(r"\s+", "", str(label or ""))
    s = re.sub(r"[^0-9A-Za-z_.-]", "", s)
    return s or f"field{idx + 1}"


def login_spec(entry: dict) -> dict:
    """抽出**该源自己声明的登录需求**（本期登录入口的数据来源）。

    返回：``{needs_cookie, vars, open_url, instructions, unsupported, actions}``
    · ``loginUi`` 的 ``type=text`` ⇒ 输入项（字段名含密钥/key/token/密码 ⇒ ``secret``）；
    · ``loginUi`` 里 ``action=set(n)`` 的按钮 ⇒ **合成一个选项组**（Legado 用同一个变量存编号）；
    · 其余按钮（``zs()`` / ``my()`` / ``get()``）⇒ 进 ``actions`` 并逐条进 ``unsupported``：
      它们是「内置浏览器里的动作」，本项目没有浏览器 ⇒ 如实说明替代做法；
    · ``loginUrl`` 是网址 ⇒ ``open_url``；是 JS ⇒ 从 ``startBrowserAwait`` 里抽地址；
    · ``bookSourceComment`` 原文进 ``instructions``（**作者写的使用方法，不改写**）。
    """
    ent = entry or {}
    needs_cookie = bool(ent.get("enabledCookieJar"))
    raw = ent.get("loginUi")
    ui = raw if isinstance(raw, list) else []
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            ui = parsed if isinstance(parsed, list) else []
        except Exception:                                 # noqa: BLE001
            ui = []

    vars_: list = []
    actions: list = []
    choices: list = []
    for i, f in enumerate(ui):
        if not isinstance(f, dict):
            continue
        label = str(f.get("name") or "").strip()
        action = str(f.get("action") or "").strip()
        if str(f.get("type")) == "text":
            secret = bool(_SECRET_HINT.search(label))
            vars_.append({"key": _var_key(label, i), "label": label or f"字段{i + 1}",
                          "type": "text", "secret": secret, "required": secret, "options": []})
        elif (m := re.match(r"^set\((\d+)\)$", action)):
            choices.append({"value": int(m.group(1)), "label": label or f"选项{m.group(1)}"})
        elif action:
            actions.append({"label": label, "action": action})
    if choices:
        # ⚠️ 合成**一个**选项组：Legado 的 `set(n)` 是往**同一个**书源变量写编号
        # （番茄那源就是「模式 / 音色」），逐条当独立开关会让用户以为能同时选。
        vars_.append({"key": "mode", "label": "模式 / 音色（书源变量）", "type": "choice",
                      "secret": False, "required": False, "options": choices})

    open_url = _login_open_url(ent)
    login_url_raw = str(ent.get("loginUrl") or "")
    unsupported: list = []
    if "startBrowserAwait" in login_url_raw:
        unsupported.append({
            "what": "内置浏览器完成验证（java.startBrowserAwait）",
            "why": "那是 Legado 的 Android 运行时动作，服务端里没有浏览器",
            "instead": (f"请在自己浏览器打开 {open_url} 访问一次完成验证，再把 Cookie 粘贴到上面的输入框"
                        if open_url else
                        "请在自己浏览器访问该站点任意页面完成验证，再把 Cookie 粘贴到上面的输入框"),
        })
    elif _JS_HEAD_RE.match(login_url_raw) and not open_url:
        unsupported.append({
            "what": "登录脚本（loginUrl 是一段 JS）",
            "why": "脚本里用了本项目无法执行的 Legado 专有 API",
            "instead": "按下面作者说明在自己浏览器完成登录，再把 Cookie / 密钥填到本页",
        })
    if "getLoginInfoMap" in login_url_raw:
        unsupported.append({
            "what": "书源密钥（source.getLoginInfoMap）",
            "why": "Legado 专有 API，服务端读不到它的登录信息表",
            "instead": "在本页的「书源变量」里填「密钥」那一项，规则里会用 {var:密钥} 引用",
        })
    for a in actions:
        unsupported.append({
            "what": f"登录面板上的按钮「{a['label']}」（{a['action']}）",
            "why": "它是内置浏览器里的动作（打开页面 / 读变量），本项目没有内置浏览器",
            "instead": "打开作者说明里的地址人工完成；结果填到本页对应的输入框 / 选项里",
        })

    return {
        "needs_cookie": needs_cookie,
        "vars": vars_,
        "open_url": open_url,
        "instructions": str(ent.get("bookSourceComment") or "").strip(),
        "unsupported": unsupported,
        "actions": actions,
    }


# ---------------- 选择器与字段转换 ----------------
#
# ⚠️ 阅读的选择器语法（`class.` / `@tag.a` / `!0` / `.0` / `##正则##替换` / `A||B` / `A&&B`）
# **不在本模块解析** —— 唯一实现是 `sources/selspec.py`，`rules.py` 执行期读的就是同一份。

def _spec_of(spec, *, drop_first_index: bool = False) -> "tuple[str, str]":
    """阅读的取值 spec → ``(写进 native 规则的 spec 文本, 人话原因)``（取不出来时文本为 ``""``）。

    ⚠️ **这里不解析选择器**：`class.` / `@tag.a` / `!0` / `.0` / `##正则##替换` / `A||B` / `A&&B`
    的唯一实现是 :mod:`novelforge.sources.selspec`，执行期（`rules.py`）读的就是同一份产物。
    本模块只做两件事：① 判**通道**（:func:`_leading_mode`：js / regex / json / css）；
    ② 用 `selspec.render` 把解析结果**写回**成 spec 文本落进规则。

    第 94 期阶段 2a 删掉了本模块原来的 `_sel_to_css` / `_field_spec` —— 那是**第二份**选择器解析，
    而且因为「非 0 索引」把整条源判死（`.odd.0` / `tr!0` 在真样本里成片出现，实测 22 条里
    6 条「判可用却一搜就抛异常」）。现在索引由引擎按「匹配列表第 n 个」执行，不再需要翻译。

    ⚠️ **解析不了时把原文原样写回去**（不是丢掉这一项）：丢掉了诚实闸就看不到它，
    用户只会收到一句笼统的「拼不出规则」—— 那正是「答非所问」。原文写回去之后，闸门能
    指名道姓：「`ruleToc.chapterList` 这一项是 XPath / 不是合法选择器，该改成什么」。
    实测三例（天天看小说 / 手机小说 / 武林中文网）就是靠这一条才拿回逐项理由的。
    """
    plan = selspec.parse_spec(spec)
    err = selspec.spec_error(plan)
    if err:
        return str(spec or "").strip(), err
    return selspec.render(plan, drop_first_index=drop_first_index), ""


def _field_of(spec) -> "tuple[str, str]":
    """**搜索字段**的取值 spec → ``(spec 文本, 人话原因)``。

    与 :func:`_spec_of` 的差别是**处理失败的方式**：字段取不出来时**略过这一项**
    （整条源不因此判死，结论降为「需留意」并带上说明）—— 少了 `author` 这种非关键字段
    不该让一条源不能用；但容器（搜索/目录/正文）取不出来就必须让闸门点名，见 `_spec_of`。
    字段取一个值时「第一个匹配」本来就是默认，所以索引按 ``drop_first_index`` 丢掉。
    """
    if not str(spec or "").strip():
        return "", ""
    plan = selspec.parse_spec(spec)
    err = selspec.spec_error(plan)
    if err:
        return "", err
    return selspec.render(plan, drop_first_index=True), ""


def _headers(entry: dict) -> dict:
    """Legado 的 ``header`` 可能是 **Python repr 形式的字典**（真实文件里就是），也可能是 JSON。

    ⚠️ 解析用 `rules.parse_dict_literal`（**唯一**一份字面量字典解析）：URL 的选项字典
    （`,{'method':…}`）走的是同一份代码 —— 各写一份的下场是一处只认单引号、另一处只认
    双引号，而**两边都不报错**（字段静默为空）。
    """
    raw = (entry or {}).get("header")
    if isinstance(raw, dict):
        return dict(raw)
    obj = rules.parse_dict_literal(raw)
    if not obj:
        return {}
    return {str(k): str(v) for k, v in obj.items()}


# ---------------- 能力判定与转换 ----------------

def _tpl(url: str) -> str:
    """Legado 模板变量 → 本项目模板变量（``{{key}}``→``{title}``、``{{page}}``→``{page}``）。"""
    s = str(url or "")
    s = re.sub(r"\{\{\s*(?:key|searchKey|query)\s*\}\}", "{title}", s, flags=re.I)
    s = re.sub(r"\{\{\s*page\s*\}\}", "{page}", s, flags=re.I)
    return s


def _leading_mode(spec: str) -> str:
    """判断一个字段的形态：``js`` / ``regex`` / ``json`` / ``xpath`` / ``css``。

    ⚠️ XPath 的判据在 :func:`selspec.is_xpath`（**唯一**一处）—— 那边刻意只认 `//…` / `.//…`
    且**排除带 `{` 的值**：实测 2.x 的 `bookUrl = /i/{$.NovelID}/`、
    `/Book/getChapterListByBookId?bookId={$._id}` 是**相对地址模板**，按「以 `/` 开头」判
    会把它们当 XPath ⇒ 取不到值，而且错得没有痕迹。
    """
    s = str(spec or "").strip()
    if _JS_HEAD_RE.match(s):
        return "js"
    if s.startswith(_REGEX_HEAD):
        return "regex"
    if s.startswith("$") or "@js:" in s.lower():
        return "json" if s.startswith("$") else "js"
    if selspec.is_xpath(s):
        return "xpath"
    return "css"


# ---------------- 全字段报告（第 94 期阶段 5）----------------

#: 阅读 3.x 字段的**全量**报告表：键（嵌套用点号）→ (状态, 原因, 替代做法)。
#:
#: **为什么要有它**：`analyze` 原先只看 5 个字段（`searchUrl` / `ruleSearch.bookList` /
#: `ruleToc.chapterList` / `ruleToc.chapterUrl` / `ruleContent.content`），其余十几项
#: **一声不响地消失** —— 用户的源里明明白白写着「详情页作者规则」，导入后那部分没了，
#: 界面上一个字都不提。所以现在这条源里**每一个出现过的字段**都要有一句交代。
#:
#: 三档状态（与 `analyze` 的 `supported` 同义）：
#:   * ``executable`` —— 引擎直接执行（转换产物里按原意保留）；
#:   * ``ported``     —— 改写了形态后使用（例如 2.x 的 `httpUserAgent` 变成请求头）；
#:   * ``unsupported``—— 本项目跑不了 / 没有这项功能，导入时被忽略（**如实说，不假装**）。
#:
#: ⚠️ 表里的键只收**实测出现过、或本项目已明确要不要做的**（样本：`202003.txt` 1537 条
#: 2.x、`tests/fixtures/legado_sample.json` 与 XIU2 `shuyuan` 的 3.x，键频统计见
#: `model.LEGACY_ALIASES` 的注释）。表外的键走**兜底**：照样逐条报「本项目未使用该字段」，
#: 不静默丢 —— 「没见过的键不许猜含义」与「见了就要如实说」是两件事。
_UNSUPPORTED = "unsupported"
_FIELD_TABLE: dict = {
    # —— 身份 / 元信息 ——
    "bookSourceName": ("executable", "落成本项目书源的展示名", ""),
    "bookSourceUrl": ("executable", "取域名白名单与请求基址", ""),
    "bookSourceGroup": ("executable", "落成本项目书源的分组", ""),
    "bookSourceComment": ("unsupported", "本项目的书源没有备注字段，导入后不保留",
                          "要留备注就写在分组名里，或到「书源管理」手写源里补"),
    "bookSourceType": ("executable", "判形态（文本 / 音频 / 漫画）", ""),
    "enabled": ("executable", "落成启用状态", ""),
    "weight": ("ported", "只存进溯源台账 —— 本项目的排序由自己的书源列表决定", ""),
    "customOrder": ("unsupported", "本项目的书源排序由自己的列表决定，源里的排序序号用不上", ""),
    "serialNumber": ("unsupported", "阅读自己的导出序号；本项目按名字与规则哈希去重，不用它", ""),
    "lastUpdateTime": ("unsupported", "阅读自己记录的时间戳；本项目的书源状态由台账维护",
                       "书源文件更新后重新导入一次即可"),
    "respondTime": ("unsupported", "阅读自己测的响应耗时；本项目的耗时来自「验证」接口", ""),
    "header": ("executable", "落成请求头（该源的每一次抓取都带它）", ""),
    "enabledCookieJar": ("unsupported", "本项目没有「书源自带 Cookie 存档」这回事",
                         "需要登录态的站点走抓取层的 CookieJar（自动保存 / 自动带上）"),
    "loginUrl": ("unsupported", "本项目没有「在服务端登录源站」的界面与流程",
                 "需要登录的源请在书源规则的请求头里带上凭据，或改用其它源"),
    "loginUi": ("unsupported", "同上：本项目没有登录界面",
                "需要交互式登录的源请在本项目里手写等价规则（带凭据的请求头）"),
    "loginCheckJs": ("unsupported", "同上：本项目没有交互式验证流程",
                     "需要验证码 / 交互验证的源请在本项目里手写等价规则"),
    "variable": ("unsupported", "本项目的规则模型里没有「变量表」这一层",
                 "把变量展开成字面量后手写进规则（地址 / 选择器里直接写死值）"),
    "jsLib": ("unsupported", "本项目的规则模型里没有「公共 JS 库」这一层",
              "把用到的函数直接写进需要它的那一项里（本项目的 JS 通道按项执行）"),
    "concurrentRate": ("ported", "换算成本项目的抓取并发上限", ""),
    # —— 发现页（项目没有这个功能，两代名字都如实说）——
    "ruleExplore": ("unsupported", "发现页规则组 —— 本项目**没有发现页功能**", ""),
    "exploreUrl": ("unsupported", "发现页地址 —— 本项目**没有发现页功能**", ""),
    "enabledExplore": ("unsupported", "同上：本项目没有发现页功能", ""),
    # —— 搜索 ——
    "searchUrl": ("executable", "搜索地址（后面的 `,{'method':…}` 请求选项由引擎自己解）", ""),
    "ruleSearch.bookList": ("executable", "搜索结果容器", ""),
    "ruleSearch.name": ("executable", "书名", ""),
    "ruleSearch.author": ("executable", "作者", ""),
    "ruleSearch.bookUrl": ("executable", "书页地址", ""),
    "ruleSearch.coverUrl": ("executable", "封面", ""),
    "ruleSearch.intro": ("executable", "简介", ""),
    "ruleSearch.kind": ("unsupported", "本项目的书目没有「分类」字段，导入后不保留",
                        "搜索本身照常可用；要按分类筛选请用本项目自己的标签 / 书库"),
    "ruleSearch.lastChapter": ("unsupported", "本项目的书目没有「最新章节」字段，导入后不保留",
                               "追更请用本项目的「检查更新」（以源站目录为准）"),
    "ruleSearch.wordCount": ("unsupported", "本项目的书目没有字数统计字段，导入后不保留", ""),
    # —— 书目信息（详情页）——
    "ruleBookInfo.tocUrl": ("executable", "目录页地址（书页上没有目录链接时用）", ""),
    "ruleBookInfo.name": ("unsupported", "详情页元数据由本项目的**刮削提供商**补齐，不用源里的规则",
                          "要用这条源的书名 / 作者，请在详情页用「元数据」里的书源刮削"),
    "ruleBookInfo.author": ("unsupported", "同上：详情页元数据由本项目的刮削提供商补齐", ""),
    "ruleBookInfo.kind": ("unsupported", "同上：本项目的书目没有「分类」字段", ""),
    "ruleBookInfo.intro": ("unsupported", "同上：简介由本项目的刮削提供商补齐", ""),
    "ruleBookInfo.coverUrl": ("unsupported", "同上：封面由本项目的刮削提供商补齐", ""),
    "ruleBookInfo.lastChapter": ("unsupported", "同上：本项目的书目没有「最新章节」字段", ""),
    "ruleBookInfo.wordCount": ("unsupported", "同上：本项目的书目没有字数统计字段", ""),
    "ruleBookInfo.init": ("unsupported", "「取详情前先发一次初始化请求」—— 本项目不支持",
                          "若站点必须先访问一次才出内容，请在书源规则里把地址改成那个页面"),
    "ruleBookInfo.bookUrlPattern": ("unsupported",
                                    "书页地址的形状校验 —— 本项目直连绑定好的地址，不做形状校验", ""),
    # —— 目录 ——
    "ruleToc.chapterList": ("executable", "目录容器", ""),
    "ruleToc.chapterName": ("executable", "章节名", ""),
    "ruleToc.chapterUrl": ("executable", "章节地址", ""),
    "ruleToc.nextTocUrl": ("executable", "目录续页", ""),
    "ruleToc.isVip": ("unsupported", "本项目的目录没有「VIP 章」标记，导入后不保留", ""),
    "ruleToc.updateTime": ("unsupported", "本项目的目录没有「章节更新时间」字段，导入后不保留", ""),
    # —— 正文 ——
    "ruleContent.content": ("executable", "正文容器", ""),
    "ruleContent.nextContentUrl": ("executable", "正文续页", ""),
    "ruleContent.replaceRegex": ("executable",
                                 "正文替换（与正文规则里的 `##正则##替换` 走**同一份**实现）", ""),
    "ruleContent.webJs": ("unsupported", "需要在浏览器环境里执行脚本 —— 本项目只发 HTTP 请求",
                          "能在脚本里算出来的地址 / 文本，请改写成选择器或模板变量"),
    "ruleContent.sourceRegex": ("unsupported", "需要浏览器环境取网页源码 —— 本项目只发 HTTP 请求",
                                "请改写成对 HTTP 响应正文生效的选择器或正则"),
}


def _report_one(field: str, value) -> dict:
    """一个字段 → ``{field, status, why, instead}``（表外的键走兜底，不静默丢）。"""
    row = _FIELD_TABLE.get(field)
    if row is None and field in EXPLORE_KEYS:
        row = ("unsupported", "发现页规则 —— 本项目**没有发现页功能**", "")
    if row is None:
        return {"field": field, "status": _UNSUPPORTED,
                "why": f"本项目不使用这个字段（{field}）—— 导入时被忽略",
                "instead": "若这一项对你的源是必需的，请在「书源管理」里手写等价规则"}
    status, why, instead = row
    return {"field": field, "status": status, "why": why, "instead": instead}


#: 需要逐子键展开的字段组（其余 dict 值按整项报告）。
_NESTED_GROUPS = ("ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent")


def field_report(entry: dict) -> list:
    """这条源里**出现过**的每一个字段 → 三档状态 + 原因 + 替代做法（阶段 5）。

    只在**入口归一之后**走一遍（2.x 的键名先变 3.x），所以同一份报告对两个方言都成立 ——
    映射表只有 `normalize_legacy` 那一份，这里不重复认方言。
    空值字段（`""` / `None` / 空表）不算「出现过」，不占篇幅。
    """
    ent = normalize_legacy(entry or {})
    out: list = []
    for key, val in ent.items():
        if key in _NESTED_GROUPS and isinstance(val, dict):
            for sub, sv in val.items():
                if sv not in (None, "", [], {}):
                    out.append(_report_one(f"{key}.{sub}", sv))
            continue
        if val in (None, "", [], {}):
            continue
        out.append(_report_one(str(key), val))
    return out


def analyze(entry: dict) -> dict:
    """逐字段判定能力 → ``{supported, unsupported_fields, converted_rule, notes, source_type}``。

    ``unsupported_fields`` 每条都给 ``field`` / ``why`` / ``instead``（**替代做法**，
    而不是只报错）—— 界面上要能把「哪一项、为什么、我该怎么做」讲清楚。

    第 94 期两处**口径变化**（都如实记在 CHANGELOG 里）：

    1. **入口先过** :func:`normalize_legacy`：阅读 2.x 的键名在这里一次归一到 3.x，
       于是全项目只有**一条**转换路（`convert` 只认 3.x 键名）。2.x 的 1537 条真实书源
       当年是**全灭**（`analyze` 一个键都读不到 ⇒ 0/1537 可转）。
    2. **`supported` 由引擎反推**：转换产物交给 ``rules.audit_native_rule`` 审，
       审计说跑不动就判 ``no``。当年是转换器自己声明可用 —— 实测 22 条样本里
       9 条判「可用」中有 **6 条**一搜就抛选择器语法异常，这就是「假可用」。
    """
    ent = normalize_legacy(entry or {})                      # ① 2.x 键名 → 3.x（唯一转换路的入口）
    unsupported: list = []
    notes: list = []
    name = str(ent.get("bookSourceName") or "").strip()
    site = str(ent.get("bookSourceUrl") or "").strip()
    stype = source_type(ent)

    if not name:
        notes.append("缺少 bookSourceName（源名），导入后会用站点兜底命名")
    if stype == "unknown":
        unsupported.append({"field": "bookSourceType", "why": f"未知类型：{ent.get('bookSourceType')}",
                            "instead": "本项目只支持文本 / 音频 / 图片（漫画）三类，请确认该源的形态"})
    if stype == "file":
        unsupported.append({"field": "bookSourceType", "why": "文件类书源本批不支持",
                            "instead": "文件类通常需要额外协议处理，建议在「书源管理」里手写规则或改用其它源"})
    if stype in ("audio", "image"):
        # 源自己声明是音频 / 漫画，而自动转换出来的规则是**文本**形态（`book.mode = "toc"`）。
        # 不判死（搜索 / 目录 / 正文这条链本身能跑），但必须说清：拿到的会是地址清单而不是正文，
        # 要真当音频 / 漫画用，得在「书源管理」里把 book.mode 改成 audio / comic。
        notes.append(f"该源声明的是{SOURCE_TYPE_LABEL.get(stype, stype)}类，而自动转换只覆盖文本形态 "
                     f"—— 导入后请到「书源管理」把「取书方式」改成 audio / comic 再填上对应规则")
    if not re.match(r"^https?://", site, re.I):
        # ⚠️ 真实文件 B 就是这种（bookSourceUrl = "大灰狼融合VIP5.0"）：Legado 允许它是任意占位串，
        # 而本项目要靠它拼请求与判域名 ⇒ 整条不可用，必须如实说清（不许猜一个域名出来）。
        unsupported.append({
            "field": "bookSourceUrl",
            "why": f"不是 http(s) 网址：{site or '(空)'}",
            "instead": "本项目以书源站点基址拼请求与判域名；请在「书源管理」里换成真实网址后重试",
        })
    explore = [k for k in EXPLORE_KEYS if str(ent.get(k) or "").strip()]
    if explore:
        # ⚠️ **只记不停**：本项目没有发现页功能（全仓没有 explore 实现），这部分规则被忽略是事实，
        #    但它不影响「搜索 → 目录 → 正文」这条主链。判死会把实测 1321 条本来能用的源误杀。
        notes.append("源里有「发现页」规则（" + "、".join(explore)
                     + "）—— 本项目没有发现页功能，这部分已忽略")

    for field, spec in (("searchUrl", ent.get("searchUrl")),
                        ("ruleSearch.bookList", (ent.get("ruleSearch") or {}).get("bookList")),
                        ("ruleToc.chapterList", (ent.get("ruleToc") or {}).get("chapterList")),
                        ("ruleToc.chapterUrl", (ent.get("ruleToc") or {}).get("chapterUrl")),
                        ("ruleContent.content", (ent.get("ruleContent") or {}).get("content"))):
        mode = _leading_mode(spec)
        if mode == "js":
            port = js_port(spec)
            if not port["ok"]:
                unsupported.append({
                    "field": field,
                    "why": "该字段是 JS，且用到本项目无法执行的 Legado 专有 API："
                           + "、".join(port["missing"]),
                    "instead": "这类源需要在手机上用「阅读」App；本项目只能请你在「书源管理」里"
                               "手写等价规则（CSS / 正则 / JSON 路径）",
                })
            else:
                notes.append(f"{field} 是 JS ⇒ 已按「可移植」处理（走 Node 通道），请留意移植后的等价性")
        if field == "ruleToc.chapterUrl" and re.search(r"\{\{\s*\$", str(spec or "")):
            unsupported.append({
                "field": field,
                "why": "章节地址要在**每条目录项**里取字段再拼装（{{$.xxx}}），本项目只支持"
                       "「目录页给的链接」或「固定模板」",
                "instead": "若站点每条目录项本身带链接，请在书源管理里改写成 url_attr；否则本批不支持",
            })

    verdict = "no" if unsupported else ("partial" if notes else "yes")
    converted = None
    if verdict != "no":
        converted = convert(ent, notes=notes)
        if converted is None:
            # ⚠️ 走到这里说明「逐字段看着都能转，却拼不出完整规则」——必须给出可读原因，
            # 否则界面会显示一个「不支持但不说为什么」的条目（与本期纪律冲突）。
            verdict = "no"
            unsupported.append({
                "field": "（整体）",
                "why": "可判定的字段不足以拼出本项目规则：搜索地址 / 目录容器 / 正文容器三者至少缺一",
                "instead": "请在「书源管理」的手动表单里补上缺的那一项（或改用其它书源）",
            })
        else:
            # ② **转换诚实闸**：产物能不能跑由引擎自己说（`rules.audit_native_rule`），
            #    不许由转换器自称可用 —— 这正是当年「9 条判可用、6 条一搜就炸」的根因。
            bad = rules.audit_native_rule(converted)
            if bad:
                verdict = "no"
                unsupported += bad
            elif notes:
                # 转换期新记下的如实说明（例如某个字段取不出来、已略过）⇒ 结论降为「需留意」，
                # 不然用户会看到一条「可用」却少了一半字段的源。
                verdict = "partial"
    return {"supported": verdict, "unsupported_fields": unsupported, "converted_rule": converted,
            "notes": notes, "source_type": stype,
            "source_type_label": SOURCE_TYPE_LABEL.get(stype, "未知"),
            # 第 94 期阶段 5：**这条源里每一个字段**的交代（三档 + 原因 + 替代做法）。
            # 与 `unsupported_fields` 刻意分开：那一位是**判定依据**（决定 verdict），
            # 这一位是**全量清单**（含跑得动的）。混在一起会让「发现页不支持」把
            # 1321 条本来能用的源判成 no —— 那是把「如实说」做成了「误杀」。
            "field_report": field_report(ent)}


def rule_name(ent: dict) -> str:
    site = norm_site(ent.get("bookSourceUrl"))
    slug = re.sub(r"[^a-z0-9._-]+", "-", site).strip("-")
    return f"lg-{slug}" if slug else f"lg-{rule_hash(ent)[:8]}"


def convert(entry: dict, notes=None) -> "dict | None":
    """把可离线确定的部分转成本项目规则（``dict``）。**调用方须保证不含 JS 专有桥**。

    产物必须能过 ``rules.validate_rule`` —— 转换不出来时返回 ``None``（调用方判 ``no``），
    绝不用一个「看着像」的规则去糊弄。
    """
    ent = entry or {}
    notes = notes if isinstance(notes, list) else []     # 逐字段的如实说明落在这里（判「需留意」）
    site = str(ent.get("bookSourceUrl") or "").strip()
    if not re.match(r"^https?://", site, re.I):
        return None
    host = urlsplit(site).hostname or ""
    if not host:
        return None
    base = site if site.endswith("/") else site + "/"

    search_url = _tpl(ent.get("searchUrl"))
    if not search_url or _JS_HEAD_RE.match(str(ent.get("searchUrl") or "")):
        return None
    # ⚠️ 地址后面**原样保留**阅读的请求选项（`/search.php,{'method':'post'}` / `?q={title}|char=gbk`）：
    #    只有引擎知道怎么发这个请求（`rules.parse_url_spec`），转换器**不翻译也不丢** ——
    #    在这里把选项摘下来、落到别的字段上，就等于转换器自己声明了一遍「哪些选项能跑」，
    #    而那正是本项目最深的那个病（转换器既当运动员又当裁判）。
    #    `urljoin` 对这样的地址是**逐字拼接**（只补主机与路径，不改查询串），所以补绝对地址
    #    与保留选项两件事不冲突。
    if not re.match(r"^https?://", search_url, re.I):
        search_url = urljoin(base, search_url.lstrip("/"))

    rs = ent.get("ruleSearch") or {}
    bl = _leading_mode(rs.get("bookList"))
    if bl not in ("css", "json", "xpath"):
        return None
    search: dict = {"url": search_url}
    if bl == "json":
        # 接口型源（如酷我小说）：搜索结果就是 JSON 数组，各字段直接给 JSON 路径
        search.update({"mode": "json", "container": str(rs.get("bookList") or "").strip()})
        fields = {k: str(v).strip() for k, v in
                  (("title", rs.get("name")), ("author", rs.get("author")),
                   ("url", rs.get("bookUrl")), ("cover", rs.get("coverUrl")),
                   ("intro", rs.get("intro")))
                  if str(v or "").strip().startswith("$")}
    elif bl == "xpath":
        # ⚠️ XPath **原样**写进规则：它有自己的语法，`selspec` 只判形状（`is_xpath`），
        #    执行由 `rules._xpath_nodes` 交给 lxml。**不翻译、不改写**（翻译 = 第二份 XPath 实现）。
        search.update({"mode": "xpath", "container": str(rs.get("bookList") or "").strip()})
        fields = {k: str(v).strip() for k, v in
                  (("title", rs.get("name")), ("author", rs.get("author")),
                   ("url", rs.get("bookUrl")), ("cover", rs.get("coverUrl")),
                   ("intro", rs.get("intro")))
                  if str(v or "").strip()}
    else:
        container, _err = _spec_of(rs.get("bookList"))
        if not container:
            return None
        search.update({"mode": "css", "container": container})
        fields = {}
        for key, spec in (("title", rs.get("name")), ("author", rs.get("author")),
                          ("url", rs.get("bookUrl")), ("cover", rs.get("coverUrl")),
                          ("intro", rs.get("intro"))):
            # ⚠️ 取不出来的字段**如实说**（写进 notes ⇒ 结论降为「需留意」），不静默丢：
            #    丢掉 `author` 这种非关键字段本身没错，但用户看不到「为什么这本没作者」。
            text, why = _field_of(spec)
            if text:
                fields[key] = text
            elif why:
                notes.append(f"ruleSearch.{key} 取不出来（{why}）—— 该字段已略过")
    if not fields.get("url"):
        return None
    search["fields"] = fields

    toc_spec = (ent.get("ruleToc") or {}).get("chapterList")
    toc_mode = _leading_mode(toc_spec)
    book: dict = {"mode": "toc"}
    if toc_mode == "json":
        book["toc"] = {"mode": "json", "container": str(toc_spec).strip()}
    elif toc_mode == "xpath":
        # 实测真源的目录容器形如 `//*[@class="chapterlist"]/dd/a`（**已经取到 `<a>`**）——
        # 不做 `_toc_container` 那种「补链接层」（那是 CSS 通道的事：容器常写 `<li>`）。
        container = str(toc_spec or "").strip()
        if not container:
            return None
        book["toc"] = {"mode": "xpath", "container": container}
    elif toc_mode == "css":
        # ⚠️ 容器**保留索引**（`drop_first_index=False`）：容器的默认是「全部匹配」，
        #    丢掉 `!0` 就从「取第一项」变成「取所有项」—— 那是取错章节的静默故障。
        toc_plan = selspec.parse_spec(toc_spec)
        toc_err = selspec.spec_error(toc_plan)
        # 解析不了的容器**原文写回**（`_spec_of` 的口径）：闸门才能指名道姓地说这一项是什么
        container = _toc_container(toc_plan, ent.get("ruleToc") or {}) if not toc_err \
            else str(toc_spec or "").strip()
        if not container:
            return None
        book["toc"] = {"mode": "css", "container": container}
    else:
        return None

    content = (ent.get("ruleContent") or {}).get("content")
    cmode = _leading_mode(content)
    if cmode == "json":
        book["content"] = {"mode": "json", "path": str(content).strip()}
    elif cmode == "xpath":
        # XPath 原文写回；正文**压纯文本**（与 css 通道的默认一致）。容器本身写成
        # `//*[@id="content"]/text()` 时取到的是文本节点列表 —— 那样也是纯文本，口径相同。
        container = str(content or "").strip()
        if not container:
            return None
        book["content"] = {"mode": "xpath", "container": container, "text": True}
    elif cmode == "js":
        # ⚠️ 只有**可移植**的 JS 才走得到这里（含 Android 专有桥的已在 :func:`analyze` 判 no）。
        # 正文交给 Node 通道：宿主脚本读 ``result``（页面 HTML）、返回正文文本 ——
        # 这条通道马上在 rules.py 里接上（本期后续节点），这里先把形状定死。
        port = js_port(content)
        if not port["ok"]:
            return None
        book["content"] = {"mode": "js", "script": port["script"]}
    elif cmode == "css":
        plan = selspec.parse_spec(content)
        cplan_err = selspec.spec_error(plan)
        container = str(content or "").strip() if cplan_err else selspec.render(plan)
        if not container:
            return None
        # Legado 的 `@html` = 保留标签；本项目 css 通道两种都支持，要如实带上
        # （不带就会把富文本压成纯文本，章节里的排版全丢）。
        book["content"] = ({"mode": "css", "container": container, "html": True}
                           if plan.mode == "html"
                           else {"mode": "css", "container": container, "text": True})
    else:
        return None

    rule = {
        "name": rule_name(ent),
        "display_name": str(ent.get("bookSourceName") or rule_name(ent)).strip(),
        "domains": [host],
        "public": False,
        "headers": _headers(ent),
        "concurrency": _concurrency(ent),
        "search": search,
        "book": book,
        "legado": {"dedup_key": dedup_key(ent), "rule_hash": rule_hash(ent),
                   "source_type": source_type(ent), "group": str(ent.get("bookSourceGroup") or ""),
                   "weight": ent.get("weight"), "concurrent_rate": ent.get("concurrentRate")},
    }
    if not rule["headers"]:
        rule.pop("headers")
    return rule


def _toc_container(plan, rule_toc: dict) -> str:
    """目录容器**补上链接层** → spec 文本（按计划补，不拼字符串）。

    ⚠️ Legado 的目录容器常写 ``<li>``，链接在它里面的 ``<a>``；而本项目的 toc 容器是直接读
    匹配到的节点的 ``href`` 与文本 —— 不补 ``a`` 会**一条章节都取不到**（静默 0 章，最难查的那种）。
    容器本身已经以 ``a`` 结尾时不补（否则会变成 ``a a``，同样取不到）。

    按**计划**补而不是按字符串补：容器可能带 ``##替换`` 尾巴（拼字符串会把 ``a`` 塞进替换段后面）、
    也可能是候选（`A||B`，两边都要补）。这些都是「静默取错」的高发区。
    """
    spec = f"{rule_toc.get('chapterUrl') or ''} {rule_toc.get('chapterName') or ''}"
    if "a" not in spec:
        return selspec.render(plan)
    return selspec.render(_with_trailing_a(plan))


def _with_trailing_a(plan):
    """在计划的取值末端补一步 ``a``（已经是 ``a`` 的不补）；候选/拼接则**每一路都补**。"""
    if plan.sub:
        return selspec.Plan(
            raw=plan.raw, sub=tuple(_with_trailing_a(s) for s in plan.sub),
            combine=plan.combine, attr=plan.attr, mode=plan.mode,
            replace=plan.replace, error=plan.error, note=plan.note)
    steps = list(plan.steps)
    if steps and steps[-1].kind == "desc" and steps[-1].css.split("[")[0].strip() == "a":
        return plan
    steps.append(selspec.Step(css="a"))
    return selspec.Plan(raw=plan.raw, steps=tuple(steps), attr=plan.attr, mode=plan.mode,
                        replace=plan.replace, error=plan.error, note=plan.note)


def _concurrency(ent: dict) -> int:
    """Legado 的 ``concurrentRate``（形如 ``"3000"`` 毫秒/次）→ 本项目并发上限的保守值。"""
    raw = ent.get("concurrentRate")
    try:
        ms = int(str(raw).strip())
    except (TypeError, ValueError):
        return 8
    if ms >= 3000:
        return 1
    if ms >= 1000:
        return 2
    return 8
