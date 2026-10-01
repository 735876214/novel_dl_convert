"""用户书源存储：读写 CONFIG_DIR/sources/*.json，并注册进 REGISTRY。

- 每条用户书源单独存一个 <name>.json 文件，便于增删与排查。
- 启动时 load_user_sources() 自动扫描目录并注册；运行时 add/remove 即时生效。
- 文件名（不含扩展名）即书源名；与内置源同名会覆盖。
"""
import json
from pathlib import Path

from .. import config
from ..core import db
from .base import REGISTRY, register
from .manager import DownloadManager
from .rules import make_rule_class, validate_rule


def _sources_dir() -> Path:
    d = config.SOURCES_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _ledger_enabled(name) -> bool:
    """台账里这个源是否启用（**没有台账行 = 启用**）—— 启停判定的唯一处。

    ⚠️ 读不到台账时**按启用处理**：数据库出问题时让书源「全部消失」比「全部可用」糟得多
    （用户会以为书源被删了）。
    """
    if not name:
        return True
    try:
        row = db.source_ledger_get(str(name))
    except Exception:                                        # noqa: BLE001
        return True
    return True if not row else bool(row.get("enabled", True))


def load_user_sources():
    """启动时加载目录内全部用户书源规则并注册。"""
    d = _sources_dir()
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] 书源文件 {f.name} 解析失败: {e}")
            continue
        rules = data if isinstance(data, list) else [data]
        for r in rules:
            if not isinstance(r, dict):
                continue
            if not _ledger_enabled(r.get("name")):
                continue          # 台账里停用的源：文件还在，但不注册（随时能再打开）
            try:
                register_rule(r)
            except Exception as e:
                print(f"[warn] 书源 {r.get('name','?')} 注册失败: {e}")


def register_rule(rule: dict):
    cls = make_rule_class(rule)
    register(cls)
    return cls


def add_rule(rule: dict) -> Path:
    """校验并写入单个书源文件，返回文件路径。"""
    errs = validate_rule(rule)
    if errs:
        raise ValueError("；".join(errs))
    d = _sources_dir()
    path = d / f"{rule['name']}.json"
    path.write_text(
        json.dumps(rule, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if _ledger_enabled(rule.get("name")):
        register_rule(rule)
    return path


def set_enabled(name: str, enabled: bool) -> tuple:
    """启停一个书源（**台账驱动的唯一入口**）。返回 ``(ok, reason)``。

    · 文件**不动**（仍在 `SOURCES_DIR`）：停用只是「不注册进 REGISTRY」—— 随时能再打开，
      也不会因为改名 / 移文件把进度与批注的坐标搞乱；
    · ⚠️ **内置源**（如 gutenberg）没有规则文件、由代码注册 ⇒ 本函数**如实拒绝**，
      而不是假装停用了（界面要把它置灰并写明原因，这是本项目的纪律）。
    """
    name = str(name)
    path = _sources_dir() / f"{name}.json"
    if not path.is_file():
        return False, "内置源由代码注册，没有可挂启停状态的规则文件"
    try:
        db.source_ledger_upsert(name, enabled=bool(enabled))
    except Exception as e:                                   # noqa: BLE001
        return False, f"写台账失败：{e}"
    if enabled:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rule = data[0] if isinstance(data, list) and data else data
            register_rule(rule)
        except Exception as e:                               # noqa: BLE001
            return False, f"重新注册失败：{e}"
    else:
        REGISTRY.pop(name, None)
    return True, ""


def remove_rule(name: str) -> bool:
    """删除用户书源（内置源不可删）。返回是否成功。"""
    REGISTRY.pop(name, None)
    path = _sources_dir() / f"{name}.json"
    if path.exists():
        try:
            path.unlink()
        except Exception:
            return False
        return True
    return False


def sources_status() -> list[dict]:
    """书源运行状态：是否可用（受 download 配置约束）+ Cookie 是否已持久化。

    Cookie 文件命名见 core/network.py：``COOKIE_DIR/<name>.cookies.txt``。
    这些是**真实可得**的状态，替代此前界面里的演示成功率 / 延迟。

    ⚠️ 「可用」的判据**只有一处**：``DownloadManager.gate_reason()``（第 71 期）。
    这里原先自己写了一段 if/elif 复刻闸门规则 —— 而真实请求路径（`/api/search`、
    `/api/download`、`/api/preview`）谁都不检查它，于是「设置说不可搜索下载、实际照搜照下」。
    现在界面显示的原因与后端拦截时用的原因是同一句原文，不会两样。
    """
    cfg = config.load_config()
    dl = cfg.get("download") or {}
    enabled = bool(dl.get("enabled", False))
    public_only = bool(dl.get("public_only", True))
    cookie_dir = Path(config.COOKIE_DIR)
    mgr = DownloadManager(cfg)

    out = []
    for s in list_sources():
        cpath = cookie_dir / f"{s['name']}.cookies.txt"
        has_cookie = cpath.is_file()
        reason = mgr.gate_reason(s["name"])
        out.append({
            **s,
            "download_enabled": enabled,
            "public_only": public_only,
            "cookie": {
                "has": has_cookie,
                "mtime": (cpath.stat().st_mtime if has_cookie else None),
                "size": (cpath.stat().st_size if has_cookie else 0),
            },
            "usable": not reason,
            "blocked_reason": reason,
        })
    return out


def list_sources() -> list[dict]:
    """列出**全部**书源：内置源 + 用户源（**含已停用的**），并合并台账（一次查询，不做 N+1）。

    台账给列表补四样东西：`enabled`（启停）、`imported`（是不是导入来的）、
    `supported`（yes / partial / no）、`group`（Legado 的 bookSourceGroup）。
    没有台账行的源按「启用 / 未导入 / 可用 / 无分组」处理 —— 手写源就是这个形态。

    ⚠️ **停用的源不在 REGISTRY**（见 :func:`set_enabled`），但它**必须出现在列表里**：
    否则界面上「停用」等于「消失」，用户再也点不回来。这类条目现场从规则文件里读
    `display_name` / `domains` / `public` 补齐 —— 文件一直都在，本来就不该丢信息。
    """
    d = _sources_dir()
    user_names = {p.stem for p in d.glob("*.json")}
    try:
        ledger = {r["name"]: r for r in db.source_ledger_all()}
    except Exception:                                        # noqa: BLE001
        ledger = {}          # 台账读不到不能让整份书源列表消失

    def _row(name: str, cls) -> dict:
        row = ledger.get(name) or {}
        if cls is not None:
            display_name = getattr(cls, "display_name", name)
            domains = list(getattr(cls, "domains", []))
            public = bool(getattr(cls, "public", True))
        else:                       # 停用的用户源：没注册，只能从文件里读
            rule = _read_rule_file(d / f"{name}.json")
            display_name = str(rule.get("display_name") or name)
            domains = [str(x) for x in (rule.get("domains") or [])]
            public = bool(rule.get("public", True))
        return {
            "name": name,
            "display_name": display_name,
            "domains": domains,
            "public": public,
            # 用户源以文件存在为准；内置源（如 gutenberg）无对应文件
            "user": name in user_names,
            "enabled": bool(row.get("enabled", True)),
            "imported": bool(row.get("imported", False)),
            "supported": row.get("supported", "yes"),
            "group": row.get("group_name", ""),
        }

    out = [_row(n, REGISTRY.get(n)) for n in sorted(set(REGISTRY) | user_names)]
    out.sort(key=lambda x: (not x["user"], x["name"]))
    return out


def _read_rule_file(path: Path) -> dict:
    """读一个规则文件（坏文件当空字典：列表少显示几个字段，总好过整页报错）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return {}
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}
