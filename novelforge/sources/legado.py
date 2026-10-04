"""Legado（「阅读」App）书源 → 本项目规则：解析 / 能力判定 / 转换 / 登录声明（第 86 期）。

## 这个模块只做四件事，且**全是纯函数、零网络**

1. :func:`parse_sources` 解析输入（数组 / 单对象 / JSONL；坏 JSON 给可读错误）；
2. :func:`analyze` **逐字段判定能力**，产出四档结论与「哪一项、为什么、替代做法」；
3. :func:`convert` 把**可离线确定**的部分转成本项目自有规则（必须能过 ``rules.validate_rule``）；
4. :func:`login_spec` 抽出**该源自己声明的登录需求**，供登录面板按声明渲染；
   另加 :func:`dedup_key` / :func:`rule_hash`（去重与「有更新」判定）与 :func:`js_port`（JS 可移植性）。

## 四档能力结论（``supported``）

- ``yes``：全靠纯字符串 URL / CSS / regex / JSONPath / 模板即可 —— 直接可用；
- ``partial``：规则可转，但**需要 JS 通道**（解密 / 文本替换 / 渲染兜底），或需要人工核对
  （非 0 索引、从 JS 里提取出来的地址）—— 会上台账并显示「需留意」；
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
from . import rules

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
#: 形如 `class.foo.0` / `id.bar` / `tag.li` 的选择器片段
_SEL_PART_RE = re.compile(r"^(class|id|tag)\.([^.@]+?)(?:\.(\d+))?$")

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

def _sel_to_css(sel: str) -> dict:
    """把 Legado 选择器片段转成 CSS：``{css, index_ok, note}``。

    支持：``class.foo`` → ``.foo``、``id.bar`` → ``#bar``、``tag.li`` → ``li``、
    ``a[data-bid]`` / ``.intro`` 原样透传（本来就是 CSS）。

    ⚠️ **非 0 索引（``.1`` / ``.2``…）本批不支持**：本项目 ``select_one`` 只能取第一个匹配，
    丢弃非 0 索引会**取到错的那一项**（比不转换更糟）⇒ 如实标注，交给人工在书源管理里改写。
    """
    s = str(sel or "").strip()
    if not s:
        return {"css": "", "index_ok": True, "note": ""}
    if "&&" in s or "||" in s:
        return {"css": "", "index_ok": False, "note": f"多路候选（&&/||）本批不支持：{s}"}
    out, note, index_ok = [], "", True
    for part in s.split("@"):
        p = part.strip()
        if not p or p in ("text", "textNodes", "html", "all"):
            continue
        m = _SEL_PART_RE.match(p)
        if m:
            kind, val, idx = m.group(1), m.group(2), m.group(3)
            if idx is not None and idx != "0":
                index_ok = False
                note = note or f"非 0 索引（{p}）本批不支持（本项目只能取第一个匹配）"
                continue
            out.append(val if kind == "tag" else (f".{val}" if kind == "class" else f"#{val}"))
            continue
        if re.match(r"^\d+$", p):        # 纯数字 = 取第 n 个后代，同样只支持 0
            if p != "0":
                index_ok = False
                note = note or f"非 0 索引（{p}）本批不支持"
            continue
        out.append(p)                    # 已是 CSS（.intro / a[data-bid] / h2）
    return {"css": " ".join(x for x in out if x), "index_ok": index_ok, "note": note}


def _field_spec(spec: str) -> dict:
    """Legado 的字段表达式 → 本项目 ``fields`` 的取值 spec（``选择器`` 或 ``选择器::attr(x)``）。

    ``class.title.0@tag.a.0@text`` 这种链式写法里，**中间每一段都是选择器的一部分**
    （这里就是「.title 里的 a」）——只取第一段会把取值位置弄错。末段是取值方式：
    ``text`` / ``textNodes`` / ``html`` 取文本，``href`` / ``src`` / ``data-*`` 取属性。
    ⚠️ 出现 ``@js:`` 的字段本批不可转（要执行脚本才能算出值）——如实拒绝，不硬猜。
    """
    s = str(spec or "").strip()
    if not s:
        return {"spec": "", "ok": True, "note": ""}
    sel_parts, tail = [], ""
    for raw in s.split("@"):
        p = raw.strip()
        if not p or p in ("text", "textNodes", "html", "all"):
            continue
        if re.match(r"^js\b|^@js", p, re.I):
            return {"spec": "", "ok": False, "note": f"字段含 JS（要执行脚本才取值）：{s}"}
        if re.match(r"^(href|src|poster|value|content|data-|alt|title$)", p):
            tail = p
            continue
        sel_parts.append(p)
    conv = _sel_to_css("@".join(sel_parts))
    if not conv["index_ok"]:
        return {"spec": "", "ok": False, "note": conv["note"]}
    css = conv["css"]
    if not css:
        return {"spec": "", "ok": False, "note": f"取不出选择器：{s}"}
    spec_out = f"{css}::attr({tail})" if tail else css
    return {"spec": spec_out, "ok": True, "note": conv["note"]}


def _headers(entry: dict) -> dict:
    """Legado 的 ``header`` 可能是 **Python repr 形式的字典**（真实文件里就是），也可能是 JSON。"""
    raw = (entry or {}).get("header")
    if isinstance(raw, dict):
        return dict(raw)
    s = str(raw or "").strip()
    if not s:
        return {}
    for parse in (ast.literal_eval, json.loads):
        try:
            obj = parse(s)
            if isinstance(obj, dict):
                return {str(k): str(v) for k, v in obj.items()}
        except Exception:                                 # noqa: BLE001
            continue
    return {}


# ---------------- 能力判定与转换 ----------------

def _tpl(url: str) -> str:
    """Legado 模板变量 → 本项目模板变量（``{{key}}``→``{title}``、``{{page}}``→``{page}``）。"""
    s = str(url or "")
    s = re.sub(r"\{\{\s*(?:key|searchKey|query)\s*\}\}", "{title}", s, flags=re.I)
    s = re.sub(r"\{\{\s*page\s*\}\}", "{page}", s, flags=re.I)
    return s


def _leading_mode(spec: str) -> str:
    """判断一个字段的形态：``js`` / ``regex`` / ``json`` / ``css``。"""
    s = str(spec or "").strip()
    if _JS_HEAD_RE.match(s):
        return "js"
    if s.startswith(_REGEX_HEAD):
        return "regex"
    if s.startswith("$") or "@js:" in s.lower():
        return "json" if s.startswith("$") else "js"
    return "css"


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
    return {"supported": verdict, "unsupported_fields": unsupported, "converted_rule": converted,
            "notes": notes, "source_type": stype,
            "source_type_label": SOURCE_TYPE_LABEL.get(stype, "未知")}


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
    if not re.match(r"^https?://", search_url, re.I):
        search_url = urljoin(base, search_url.lstrip("/"))

    rs = ent.get("ruleSearch") or {}
    bl = _leading_mode(rs.get("bookList"))
    if bl not in ("css", "json"):
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
    else:
        conv = _sel_to_css(rs.get("bookList"))
        if not conv["css"] or not conv["index_ok"]:
            return None
        search.update({"mode": "css", "container": conv["css"]})
        fields = {}
        for key, spec in (("title", rs.get("name")), ("author", rs.get("author")),
                          ("url", rs.get("bookUrl")), ("cover", rs.get("coverUrl")),
                          ("intro", rs.get("intro"))):
            f = _field_spec(spec)
            if f["ok"] and f["spec"]:
                fields[key] = f["spec"]
    if not fields.get("url"):
        return None
    search["fields"] = fields

    toc_spec = (ent.get("ruleToc") or {}).get("chapterList")
    toc_mode = _leading_mode(toc_spec)
    book: dict = {"mode": "toc"}
    if toc_mode == "json":
        book["toc"] = {"mode": "json", "container": str(toc_spec).strip()}
    elif toc_mode == "css":
        conv = _sel_to_css(toc_spec)
        if not conv["css"] or not conv["index_ok"]:
            return None
        book["toc"] = {"mode": "css",
                       "container": _toc_container(conv["css"], ent.get("ruleToc") or {})}
    else:
        return None

    content = (ent.get("ruleContent") or {}).get("content")
    cmode = _leading_mode(content)
    if cmode == "json":
        book["content"] = {"mode": "json", "path": str(content).strip()}
    elif cmode == "js":
        # ⚠️ 只有**可移植**的 JS 才走得到这里（含 Android 专有桥的已在 :func:`analyze` 判 no）。
        # 正文交给 Node 通道：宿主脚本读 ``result``（页面 HTML）、返回正文文本 ——
        # 这条通道马上在 rules.py 里接上（本期后续节点），这里先把形状定死。
        port = js_port(content)
        if not port["ok"]:
            return None
        book["content"] = {"mode": "js", "script": port["script"]}
    elif cmode == "css":
        conv = _sel_to_css(content)
        if not conv["css"] or not conv["index_ok"]:
            return None
        # Legado 的 `@html` = 保留标签；本项目 css 通道两种都支持，要如实带上
        # （不带就会把富文本压成纯文本，章节里的排版全丢）。
        if re.search(r"@\s*html\s*$", str(content or ""), re.I):
            book["content"] = {"mode": "css", "container": conv["css"], "html": True}
        else:
            book["content"] = {"mode": "css", "container": conv["css"], "text": True}
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


def _toc_container(css: str, rule_toc: dict) -> str:
    """目录容器**补上链接层**。

    ⚠️ Legado 的目录容器常写 ``<li>``，链接在它里面的 ``<a>``；而本项目的 toc css 是直接读
    容器自身的 ``href`` 与文本 —— 不补 ``a`` 会**一条章节都取不到**（静默 0 章，最难查的那种）。
    容器本身已经是 ``a`` 时不补（否则会变成 ``a a``，同样取不到）。
    """
    spec = f"{rule_toc.get('chapterUrl') or ''} {rule_toc.get('chapterName') or ''}"
    if "a" not in spec:
        return css
    parts = css.split()
    if parts and parts[-1].split("[")[0] == "a":
        return css
    return f"{css} a"


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
