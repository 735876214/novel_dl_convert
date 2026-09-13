"""用户书源存储：读写 CONFIG_DIR/sources/*.json，并注册进 REGISTRY。

- 每条用户书源单独存一个 <name>.json 文件，便于增删与排查。
- 启动时 load_user_sources() 自动扫描目录并注册；运行时 add/remove 即时生效。
- 文件名（不含扩展名）即书源名；与内置源同名会覆盖。
"""
import json
from pathlib import Path

from .. import config
from .base import REGISTRY, register
from .rules import make_rule_class, validate_rule


def _sources_dir() -> Path:
    d = config.SOURCES_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


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
    register_rule(rule)
    return path


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


def list_sources() -> list[dict]:
    """列出全部已注册书源，标注是否为用户源。"""
    d = _sources_dir()
    user_names = {p.stem for p in d.glob("*.json")}
    out = []
    for name, cls in REGISTRY.items():
        # 用户源以文件存在为准；内置源（如 gutenberg）无对应文件
        out.append(
            {
                "name": name,
                "display_name": getattr(cls, "display_name", name),
                "domains": list(getattr(cls, "domains", [])),
                "public": bool(getattr(cls, "public", True)),
                "user": name in user_names,
            }
        )
    out.sort(key=lambda x: (not x["user"], x["name"]))
    return out
