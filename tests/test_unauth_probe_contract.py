"""未登录访客**不发注定 401 的探测请求**（第 91 期）。

## 缺陷形态

冷访问（从没登录过 / 清过 localStorage）时，`App.vue` 的 `showLogin` 初值写死
`false` ⇒ **门禁还没裁决，外壳就已经渲染了**，外壳里的 store 各自开拉，白发一轮
注定 401 的探测请求。600 本库实测：`collections` / `libraries` / `smart-scopes` /
`features` / `browse-counts` / `notifications` / `prefs/*` / `config` 各被调 **2 次**，
多出来的那次全是未带 token 的 401 探测（每个约 337 B —— 低于 gzip 的
`minimum_size=1024`，所以连压缩都省不下来）。

⚠️ 修的时候有个**极易漏**的点：`App.vue` 自己 `onMounted` 里的
`tasks.refresh()`（→ `/api/tasks`）与 `library.loadLibraries()`（→ `/api/libraries`）
**不受模板 `v-if/v-else` 控制** —— 它们是 App.vue 级、无条件执行的。
只把 `showLogin` 初值改掉，实测是 **12 → 2**，剩的正是这两个。

## 所以钉四件事（任一漂移都该红）

1. `showLogin` 初值 = `!auth.authenticated`（同步读本地 token，**零延迟** ——
   第 68 期权衡里被否掉的是「等 `api.me()`」，不是「读本地 token」）。
2. 外壳首拉收进 `bootstrapShell()`，且**只在已登录分支**执行。
3. `LoginGate` 的 `@authed` → `onAuthed`，且 `onAuthed` **必须补跑一次**
   `bootstrapShell()` —— 漏了不报错，表现只是「登录进来后任务栏永远空着」。
4. `tasks.refresh()` / `library.loadLibraries()` 全文件**各只出现一次**
   （都在 `bootstrapShell` 里）—— 防止日后有人在 `onMounted` 里顺手再加一处。

与 `test_first_run_contract.py` 同一套做法：仓内前端契约用 pytest 读源码校验。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
APP_VUE = SRC / "App.vue"
AUTH_STORE = SRC / "stores" / "auth.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """去掉注释后的源码。

    本文件要断言「某处**只出现一次**」，而解释这条规则的注释里必然反复提到
    `tasks.refresh()` / `library.loadLibraries()` —— 不剥注释就会把注释当成违规。
    """
    src = _read(p)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)   # /* ... */ 与 /** 文档块 */
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)   # 整行 //
    return re.sub(r"//[^\n]*", "", src)               # 行尾 //


def _fn_body(src: str, name: str) -> str:
    """从 `function <name>(…)` 取到配对的收尾花括号（够用，不引 JS 解析器）。"""
    m = re.search(rf"function {name}\([^)]*\)[^{{]*\{{", src)
    assert m, f"找不到函数 {name}，请同步本测试"
    i = m.end()
    depth = 1
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[m.end() : i - 1]


# ---------------------------------------------------------------------------
# ① 判据：本地 token 决定初值（不是写死的 false）
# ---------------------------------------------------------------------------

def test_门禁初值取本地_token():
    src = _code(APP_VUE)
    assert re.search(r"const showLogin\s*=\s*ref\(\s*false\s*\)", src) is None, (
        "showLogin 初值不许再写死 false —— 那会让未登录访客先渲染一次外壳、白发一轮 401 探测"
    )
    assert re.search(r"const showLogin\s*=\s*ref\(!auth\.authenticated\)", src), (
        "showLogin 初值必须是 `!auth.authenticated`（同步读本地 token，零延迟）"
    )


def test_本地_token_在_store_构造期同步可读():
    """这条初值成立的**前提**：`auth.authenticated` 在 setup 期就已知。

    若哪天把它改成异步（比如从 `/api/me` 回填），上面那条初值就会变成「永远是 true」，
    门禁再也关不掉 —— 所以把前提一并钉住。
    """
    src = _read(AUTH_STORE)
    assert "localStorage.getItem(TOKEN_KEY)" in src, "token 必须在 state 初始化时就同步读出来"
    m = re.search(r"authenticated:\s*\(s\)\s*=>\s*!!s\.token", src)
    assert m, "authenticated 必须由同步的 token 派生"


# ---------------------------------------------------------------------------
# ② 外壳首拉收进 bootstrapShell，且只在已登录分支调用
# ---------------------------------------------------------------------------

def test_外壳首拉收进单一函数():
    src = _code(APP_VUE)
    body = _fn_body(src, "bootstrapShell")
    assert "tasks.refresh()" in body, "任务首拉要在这里"
    assert "library.loadLibraries()" in body, "书库首拉要在这里（它同时是引导弹窗的触发源）"


def test_app_级请求各只出现一次():
    """`App.vue` 自己的两个请求不许再出现第二处调用。

    它们**不受模板 `v-if/v-else` 控制** —— 多一处就是「未登录时多两个 401 探测」。
    """
    src = _code(APP_VUE)
    assert src.count("tasks.refresh()") == 1, (
        f"tasks.refresh() 应只在 bootstrapShell 里调用一次，实际 {src.count('tasks.refresh()')} 次"
    )
    assert src.count("library.loadLibraries()") == 1, (
        f"library.loadLibraries() 应只在 bootstrapShell 里调用一次，实际 {src.count('library.loadLibraries()')} 次"
    )


def test_首拉被已登录判据挡住():
    src = _code(APP_VUE)
    m = re.search(r"onMounted\(async \(\) => \{(.*?)\n\}\)", src, re.S)
    assert m, "onMounted 的形状变了，请同步本测试"
    body = m.group(1)
    assert "auth.init()" in body, "挂载时仍要裁决鉴权"
    assert "showLogin.value = !auth.authenticated" in body, "裁决结果要写回门禁"
    call = body.find("bootstrapShell()")
    assert call >= 0, "已登录分支要调 bootstrapShell()"
    head = body[:call]
    assert "!showLogin.value" in head or "auth.authenticated" in head, (
        "bootstrapShell() 必须被「已登录」判据挡住 —— 否则未登录访客照样白发两个 401"
    )
    assert body.rindex("!showLogin.value") < call, "判据要在调用之前"


# ---------------------------------------------------------------------------
# ③ 登录成功后必须补跑一次（最易漏的一条）
# ---------------------------------------------------------------------------

def test_登录成功后补跑外壳首拉():
    src = _code(APP_VUE)
    assert re.search(r'<LoginGate[^>]*@authed="onAuthed"', src), (
        "LoginGate 的 @authed 要绑到 onAuthed（不再是就地一句 `showLogin = false`）"
    )
    body = _fn_body(src, "onAuthed")
    assert "showLogin.value = false" in body, "先把门禁关掉"
    assert "bootstrapShell()" in body, (
        "登录后必须补跑 bootstrapShell() —— 漏了不会报错，只是任务栏永远空着、书库列表不刷新"
    )
