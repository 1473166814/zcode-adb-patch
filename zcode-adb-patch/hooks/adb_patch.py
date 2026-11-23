#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zcode-adb-patch：让 ZCode 的 Bash 工具不再拒绝它解析不到的 adb 命令。

原理：ZCode 引擎（resources/glm/zcode.cjs）执行 Bash 命令前，会把裸 adb 改写成 SDK 里 adb 的
绝对路径；解析不到（adb 在工作区内 / 哪里都找不到 / 执行适配器不支持解析）时直接拒绝执行。
本工具只改引擎里与 adb 有关的三处：把三种"拒绝"改成"跳过改写、命令原样交给 shell"，并去掉
Bash 工具描述里"工作区内 adb 被禁止"的说法。引擎其它字节不动，可按打补丁时记下的原文精确还原。

用法：
    adb_patch.py patch                SessionStart：确保引擎补丁在位（ZCode 升级后自动重打）
    adb_patch.py self-update [--force] SessionStart：经宿主官方 CLI 检查并安装插件更新
    adb_patch.py status               查看引擎补丁状态
    adb_patch.py restore              三处改动还原为原文，并停止自动打补丁
    adb_patch.py config [--patch on|off] [--auto-update on|off]

原则：
- 只认每版不变的文字（文案、报错消息）做锚点；语句里压缩后的变量名每版会变，用正则捕获。
- 三处必须要么都是"原文"、要么都是"已打过"；任何一处找不到、出现多次或被别的补丁改过，
  整体拒绝改动。
- 先在副本上改并做语法检查，通过后才替换引擎；替换前确认引擎没被别的进程改过，替换后回读确认
  （zcode-auto-compact 等别的补丁也会改同一个文件）。
- hook 模式不往标准输出写任何内容（宿主把标准输出当 JSON 严格解析），诊断一律走 stderr；
  任何异常都吞掉并以 0 退出，不干扰会话。

用户设置存放在 ~/.zcode/zcode-adb-patch/config.json。

相关环境变量（均可选）：
- ZCODE_WINDOWS_APP_INSTALL_DIR   ZCode 安装目录（定位引擎与自带运行时）
- ZCODE_ADB_PATCH_DATA            数据目录（缺省 ~/.zcode/zcode-adb-patch）
- ZCODE_ADB_PATCH_CONFIG          用户设置文件路径（覆盖默认位置）
- ZCODE_ADB_PATCH_ENGINE          引擎文件路径（覆盖默认位置，仅用于测试）
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

PLUGIN_NAME = "zcode-adb-patch"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()
DATA_DIR = Path(os.environ.get("ZCODE_ADB_PATCH_DATA") or HOME / ".zcode" / PLUGIN_NAME)
PLUGINS_DIR = HOME / ".zcode" / "cli" / "plugins"
ZCODE_CJS = Path("resources") / "glm" / "zcode.cjs"

DEFAULTS = {
    "patchEnabled": True,    # False：不打补丁（restore 会置为 False）
    "autoUpdate": True,      # 新会话检查插件更新（经宿主官方 CLI）
    "autoUpdateIntervalMinutes": 60,   # 两次自动检查的最小间隔
}
MAX_ATTEMPTS = 3             # 引擎被别的进程同时改写时的重试次数
SETTLE_SECONDS = 1.0         # 替换后等这么久再回读，确认没被别的进程覆盖

FOREIGN_MSG = ("引擎里的 adb 相关代码不是已知形状（ZCode 升级后代码有变，或被别的补丁修改），未改动；"
               "需要重新分析新版引擎后再更新锚点")

# 标识符：压缩后的名字可能以 $ 开头（4.0.0 起）
ID = rb"[\w$]+"

# 三处修改。old=原文的形状（每版不变的文字逐字匹配，变量名用命名组捕获）；new=打过补丁后的形状
# （用于识别"已打过"并定位还原位置）；make=由原文的匹配生成新语句。
# 引擎原文示例（4.0.0，变量名每版会变）：
#   if(v.status!=="resolved")throw Mr(v.status==="workspace"?qn.PermissionDenied:qn.ConfigurationError,…);
#   if(!_)throw Mr(qn.ConfigurationError,"Execution adapter cannot resolve adb safely");
EDITS = [
    {
        "name": "Bash 工具描述",
        "old": re.compile(rb"- Workspace-controlled adb executables are blocked\. Installed SDK adb outside the workspace is allowed; bare adb"),
        "new": re.compile(rb"- adb commands are allowed, including workspace-controlled adb executables; bare adb"),
        "make": lambda m: b"- adb commands are allowed, including workspace-controlled adb executables; bare adb",
    },
    {
        "name": "工作区内 / 找不到 adb 时拒绝执行",
        "old": re.compile(
            rb'if\((?P<s>' + ID + rb')\.status!=="resolved"\)throw (?P<t>' + ID + rb')\((?P=s)\.status==="workspace"\?'
            rb'(?P<n>' + ID + rb')\.PermissionDenied:(?P=n)\.ConfigurationError,(?P=s)\.status==="workspace"\?'
            rb'"Workspace-controlled adb execution is blocked\. Use an installed SDK outside the workspace\.":'
            rb'"adb was not found outside the workspace\. Configure Android SDK/PATH or use an installed SDK absolute path\.",'
            rb'\{context:\{reason:(?P=s)\.status==="workspace"\?"workspace-adb-blocked":"adb-not-found"\},recoverable:!0\}\);'),
        "new": re.compile(rb'if\((?P<s>' + ID + rb')\.status!=="resolved"\)continue;'),
        "make": lambda m: b'if(' + m.group("s") + b'.status!=="resolved")continue;',
    },
    {
        "name": "执行适配器不支持解析时拒绝执行",
        "old": re.compile(
            rb'if\(!(?P<r>' + ID + rb')\)throw (?P<t>' + ID + rb')\((?P<n>' + ID + rb')\.ConfigurationError,'
            rb'"Execution adapter cannot resolve adb safely"\);'),
        # 新串本身太通用，连着前面的方法名一起认；skip=定位之后真正要还原的那一段的起点
        "new": re.compile(rb'resolveAdbExecutable;if\(!(?P<r>' + ID + rb')\)continue;'),
        "skip": len(b"resolveAdbExecutable;"),
        "make": lambda m: b'if(!' + m.group("r") + b')continue;',
    },
]


def log_err(msg):
    print(msg, file=sys.stderr)


# ---------- 配置 ----------

def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def user_config_path():
    return Path(os.environ.get("ZCODE_ADB_PATCH_CONFIG") or DATA_DIR / "config.json")


def load_config():
    cfg = dict(DEFAULTS)
    raw = _read_json(user_config_path())
    if isinstance(raw, dict):
        for k in DEFAULTS:
            if raw.get(k) is not None:
                cfg[k] = raw[k]
    cfg["patchEnabled"] = cfg["patchEnabled"] is not False
    cfg["autoUpdate"] = cfg["autoUpdate"] is not False
    try:
        cfg["autoUpdateIntervalMinutes"] = max(5, int(cfg["autoUpdateIntervalMinutes"]))
    except (TypeError, ValueError):
        cfg["autoUpdateIntervalMinutes"] = 60
    return cfg


def save_user_config(changes):
    path = user_config_path()
    raw = _read_json(path)
    if not isinstance(raw, dict):
        raw = {}
    raw.update(changes)
    _write_json(path, raw)


def plugin_version():
    try:
        return str((_read_json(PLUGIN_ROOT / ".zcode-plugin" / "plugin.json") or {}).get("version") or "?")
    except Exception:
        return "?"


def record_run(mode):
    """记录最近一次运行，供 status 显示「插件是否在正常工作」。"""
    try:
        _write_json(DATA_DIR / "last-run.json", {
            "time": time.time(), "mode": mode, "version": plugin_version(), "root": str(PLUGIN_ROOT)})
    except Exception:
        pass


# ---------- 定位 ZCode ----------

def locate_zcode_cli(cfg):
    """定位宿主（ZCode.exe 与引擎 zcode.cjs）。"""
    cands = []
    if os.environ.get("ZCODE_WINDOWS_APP_INSTALL_DIR"):
        cands.append(Path(os.environ["ZCODE_WINDOWS_APP_INSTALL_DIR"]))
    try:
        for mf in PLUGINS_DIR.glob("cache/*/*/*/.zcode-plugin/plugin.json"):   # 官方插件 manifest 里记有宿主绝对路径
            servers = (_read_json(mf) or {}).get("mcpServers")
            exe = str((servers.get("documents") or {}).get("command") or "") if isinstance(servers, dict) else ""
            if exe.endswith("ZCode.exe"):
                cands.append(Path(exe).parent)
                break
    except OSError:
        pass
    for base in cands:
        exe, entry = base / "ZCode.exe", base / ZCODE_CJS
        if exe.is_file() and entry.is_file():
            return exe, entry
    return None


def engine_path(cfg):
    if os.environ.get("ZCODE_ADB_PATCH_ENGINE"):
        return Path(os.environ["ZCODE_ADB_PATCH_ENGINE"])
    cli = locate_zcode_cli(cfg)
    return cli[1] if cli else None


# ---------- 插件自更新（经宿主官方 CLI） ----------

def _installed_entry():
    data = _read_json(PLUGINS_DIR / "installed_plugins.json") or {}
    for p in data.get("plugins") or []:
        if isinstance(p, dict) and p.get("name") == PLUGIN_NAME:
            return p
    return None


def _run_cli(args, timeout=40):
    cli = locate_zcode_cli(load_config())
    if not cli:
        return None
    exe, entry = cli
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    return subprocess.run([str(exe), str(entry)] + args, env=env, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout)


def _preflight(market, source):
    """安装前对市场副本里的新版本做语法预检：坏版本不装。"""
    root = PLUGINS_DIR / "marketplaces" / str(market or "") / (source if isinstance(source, str) else PLUGIN_NAME)
    f = root / "hooks" / "adb_patch.py"
    if not f.is_file():
        return ""
    try:
        compile(f.read_text(encoding="utf-8"), str(f), "exec")
    except (SyntaxError, UnicodeDecodeError) as exc:
        return "hooks/adb_patch.py: {}".format(exc)
    return ""


def _acquire_lock(path):
    for _ in range(2):
        try:
            os.close(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:   # 超过 5 分钟视为残留锁
                if time.time() - path.stat().st_mtime > 300:
                    path.unlink()
                    continue
            except OSError:
                pass
            return False
        except OSError:
            return True   # 无法加锁时不因此跳过更新
    return False


def _run_update(cfg, inst):
    out = {"time": time.time()}
    market = inst.get("marketplace") or ""
    plugin_id = inst.get("id") or "{}@{}".format(PLUGIN_NAME, market)
    if market:
        r = _run_cli(["plugins", "marketplace", "update", market, "--json"])
        if r is None:
            log_err("zcode-adb-patch: 找不到 ZCode 宿主 CLI，跳过自动更新")
            return dict(out, lastResult="cli-not-found")
        if r.returncode != 0:
            return dict(out, lastResult="marketplace-refresh-failed", detail=(r.stderr or r.stdout)[-400:])
    bad = _preflight(market, inst.get("source"))
    if bad:
        log_err("zcode-adb-patch: 新版本语法预检失败，不安装：{}".format(bad))
        return dict(out, lastResult="preflight-failed", detail=bad)
    r = _run_cli(["plugins", "update", plugin_id, "--json"])
    if r is None:
        return dict(out, lastResult="cli-not-found")
    text = (r.stdout or "").strip()
    try:
        data = json.loads(text.splitlines()[-1]) if text else {}   # --json 输出；拿不到 JSON 时按文本处理
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    if r.returncode != 0 or data.get("ok") is False:
        return dict(out, lastResult="failed", detail=(r.stderr or text)[-400:])
    before = inst.get("version")
    after = (_installed_entry() or {}).get("version") or data.get("version") or before
    return dict(out, lastResult="updated" if after != before else "up-to-date",
                fromVersion=before, version=after, detail=text[-200:])


def do_self_update(force=False):
    cfg = load_config()
    if not force and not cfg.get("autoUpdate", True):
        return
    inst = _installed_entry()   # 尚未安装（直接从源码目录运行）时无需更新
    if not inst:
        return
    now = time.time()
    ufile, lock = DATA_DIR / "update.json", DATA_DIR / "update.lock"
    st = _read_json(ufile) or {}
    if not isinstance(st, dict):
        st = {}
    try:
        elapsed = now - float(st.get("lastCheck") or 0)
    except (TypeError, ValueError):
        elapsed = None
    if not force and elapsed is not None and 0 <= elapsed < int(cfg["autoUpdateIntervalMinutes"]) * 60:
        return
    st["lastCheck"] = now
    if not _acquire_lock(lock):
        _write_json(ufile, st)
        return
    try:
        st.update(_run_update(cfg, inst))
    except Exception as exc:
        st["lastResult"], st["detail"] = "failed", repr(exc)[:400]
    finally:
        try:
            _write_json(ufile, st)
        except Exception:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


# ---------- 引擎补丁 ----------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(data):
    """返回 (整体状态, 每处的匹配)。整体状态：patched=三处都已打过；clean=三处都是原文；foreign=其它。"""
    edits = []
    for e in EDITS:
        old, new = list(e["old"].finditer(data)), list(e["new"].finditer(data))
        if len(old) == 1 and not new:
            edits.append({"edit": e, "state": "clean", "match": old[0]})
        elif len(new) == 1 and not old:
            edits.append({"edit": e, "state": "patched", "match": new[0]})
        else:
            edits.append({"edit": e, "state": "foreign", "match": None})
    states = {x["state"] for x in edits}
    return (states.pop() if len(states) == 1 else "foreign"), edits


def _span(x):
    """这一处要被替换的区间。"""
    m = x["match"]
    skip = x["edit"].get("skip", 0) if x["state"] == "patched" else 0
    return m.start() + skip, m.end()


def _rest(data, edits):
    """去掉这几处之后的其余字节，用来确认改动只落在这几处。"""
    for x in sorted(edits, key=_span, reverse=True):
        s, e = _span(x)
        data = data[:s] + data[e:]
    return data


def _build_patched(data, edits):
    """原文 → 打过补丁的内容，并返回补丁记录。自检：结果须是 patched 形状、这几处以外字节不变。"""
    out, originals = data, [None] * len(EDITS)
    for i in sorted(range(len(edits)), key=lambda k: edits[k]["match"].start(), reverse=True):
        m = edits[i]["match"]
        originals[i] = m.group(0)
        out = out[:m.start()] + edits[i]["edit"]["make"](m) + out[m.end():]
    n2, n3 = edits[1]["match"].groupdict(), edits[2]["match"].groupdict()
    rec = {
        "names": {"status": n2["s"].decode(), "thrower": n2["t"].decode(), "errns": n2["n"].decode(),
                  "resolver": n3["r"].decode()},
        "originals": [base64.b64encode(t).decode() for t in originals],
    }
    state, edits2 = inspect(out)
    if state != "patched" or _rest(data, edits) != _rest(out, edits2):
        raise ValueError("补丁自检失败")
    return out, rec


def _build_restored(data, edits, rec):
    """打过补丁的内容 → 原文：把补丁记录里的原文逐字节放回，并自检结果是 clean 形状。"""
    try:
        originals = [base64.b64decode(x) for x in rec["originals"]]
        names = rec["names"]
    except Exception as exc:
        raise ValueError("补丁记录损坏：{!r}".format(exc))
    if len(originals) != len(EDITS):
        raise ValueError("补丁记录与当前的补丁定义不匹配")
    if (edits[1]["match"].group("s").decode(), edits[2]["match"].group("r").decode()) != \
            (names.get("status"), names.get("resolver")):
        raise ValueError("引擎里的补丁与补丁记录对不上")
    # 按在文件里的实际位置从后往前替换，前面的替换才不会推走后面的偏移
    out = data
    for i in sorted(range(len(EDITS)), key=lambda k: _span(edits[k])[0], reverse=True):
        s, e = _span(edits[i])
        out = out[:s] + originals[i] + out[e:]
    state, edits2 = inspect(out)
    if state != "clean" or _rest(data, edits) != _rest(out, edits2):
        raise ValueError("还原结果自检失败")
    return out


def _syntax_check(path, cfg):
    """用 ZCode 自带的运行时对副本做语法检查。运行时起不来时跳过（返回 ok 与说明）；不通过则不放行。"""
    cli = locate_zcode_cli(cfg)
    if not cli:
        return True, "skipped（找不到 ZCode 运行时）"
    try:
        r = subprocess.run([str(cli[0]), "--check", str(path)], env=dict(os.environ, ELECTRON_RUN_AS_NODE="1"),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return True, "skipped（{!r}）".format(exc)
    return r.returncode == 0, "ok" if r.returncode == 0 else (r.stderr or "")[-300:]


def _drop(tmp):
    try:
        tmp.unlink()
    except OSError:
        pass


def _commit(path, before, after, cfg):
    """把引擎从 before 换成 after：副本语法检查 → 确认引擎仍是 before → 原子替换 → 回读确认。
    返回 None 表示成功；带 retry 表示引擎被别的进程改了、需要重读重来；带 error 表示放弃。"""
    # 副本必须保留引擎原本的扩展名（.cjs），否则运行时的 --check 不认
    tmp = path.with_name(path.name + ".zcode-adb-patch.tmp" + path.suffix)
    try:
        tmp.write_bytes(after)
        if tmp.read_bytes() != after:
            raise OSError("副本写入不完整")
        ok, err = _syntax_check(tmp, cfg)
        if not ok:
            return {"error": "语法检查未通过，未改动引擎：{}".format(err)}
        if path.read_bytes() != before:
            return {"retry": "替换前发现引擎已被别的进程修改"}
        os.replace(tmp, path)
    except OSError as exc:
        return {"error": "写入引擎文件失败：{}".format(exc)}
    finally:   # 中途放弃时清掉副本；替换成功后副本已不存在
        _drop(tmp)
    time.sleep(SETTLE_SECONDS)
    if path.read_bytes() != after:
        return {"retry": "替换后引擎又被别的进程改写"}
    return None


def _forget_engine():
    try:
        (DATA_DIR / "patch-record.json").unlink()
    except OSError:
        pass


def status_of(path, data, cfg):
    """引擎补丁状态。"""
    state, edits = inspect(data)
    rec = _read_json(DATA_DIR / "patch-record.json")
    info = {"path": str(path), "patchEnabled": bool(cfg.get("patchEnabled", True)), "state": state,
            "edits": [{"name": x["edit"]["name"], "state": x["state"]} for x in edits],
            "hasRecord": bool(isinstance(rec, dict) and rec.get("originals"))}
    if info["hasRecord"]:
        info["appliedAt"] = rec.get("time")
        info["zcodeBuild"] = rec.get("zcodeBuild")
    run = _read_json(DATA_DIR / "last-run.json")
    if isinstance(run, dict) and run.get("time"):
        info["lastRunAt"] = run["time"]
        info["lastRunVersion"] = run.get("version")
    if state == "patched" and not info["hasRecord"]:
        info["note"] = "补丁在位，但不是本插件打的（多半是 re-patch-adb.sh 脚本）；本插件的 restore 需要自己的补丁记录"
    return info


def status(cfg):
    path = engine_path(cfg)
    if not path or not path.is_file():
        return {"path": str(path) if path else None, "state": "missing", "error": "找不到 ZCode 引擎文件"}
    return status_of(path, path.read_bytes(), cfg)


def apply_patch(cfg):
    """确保引擎带着 adb 补丁。"""
    path = engine_path(cfg)
    if not path or not path.is_file():
        return {"state": "missing", "error": "找不到 ZCode 引擎文件"}
    for _ in range(MAX_ATTEMPTS):
        data = path.read_bytes()
        state, edits = inspect(data)
        if state == "patched":
            return dict(status_of(path, data, cfg), changed=False)
        if state != "clean":
            return dict(status_of(path, data, cfg), error=FOREIGN_MSG)
        try:
            after, rec = _build_patched(data, edits)
        except ValueError as exc:
            return dict(status_of(path, data, cfg), error=str(exc))
        res = _commit(path, data, after, cfg)
        if res is None:
            rec.update(time=time.time(), path=str(path), zcodeBuild=os.environ.get("ZCODE_APP_VERSION"),
                       cleanSha256=_sha(data), patchedSha256=_sha(after))
            try:   # 打补丁前的引擎留一份，仅供人工排查；还原不依赖它
                bak = DATA_DIR / "engine-backup" / ("zcode.cjs." + rec["cleanSha256"][:16])
                if not bak.exists():
                    bak.parent.mkdir(parents=True, exist_ok=True)
                    bak.write_bytes(data)
            except OSError:
                pass
            try:
                _write_json(DATA_DIR / "patch-record.json", rec)
            except OSError:
                pass
            return dict(status_of(path, after, cfg), changed=True, cleanSha256=rec["cleanSha256"])
        if "retry" not in res:
            return dict(status_of(path, path.read_bytes(), cfg), error=res["error"])
    return {"state": "error", "path": str(path),
            "error": "引擎正被其它进程同时改写，重试 {} 次仍未成功；下个会话会再试".format(MAX_ATTEMPTS)}


def restore_engine(cfg):
    """把三处改动还原为原文。"""
    path = engine_path(cfg)
    if not path or not path.is_file():
        return {"state": "missing", "error": "找不到 ZCode 引擎文件"}
    rec = _read_json(DATA_DIR / "patch-record.json")
    for _ in range(MAX_ATTEMPTS):
        data = path.read_bytes()
        state, edits = inspect(data)
        if state == "clean":
            _forget_engine()
            return dict(status_of(path, data, cfg), changed=False)
        if state != "patched":
            return dict(status_of(path, data, cfg), error=FOREIGN_MSG)
        if not (isinstance(rec, dict) and rec.get("originals")):
            return dict(status_of(path, data, cfg), error=(
                "引擎带着 adb 补丁，但本插件没有它的补丁记录（多半是 re-patch-adb.sh 脚本打的）。"
                "要还原请用 restore-adb.sh；ZCode 升级后会改由本插件重打"))
        try:
            after = _build_restored(data, edits, rec)
        except ValueError as exc:
            return dict(status_of(path, data, cfg), error=str(exc))
        res = _commit(path, data, after, cfg)
        if res is None:
            _forget_engine()
            return dict(status_of(path, after, cfg), changed=True)
        if "retry" not in res:
            return dict(status_of(path, path.read_bytes(), cfg), error=res["error"])
    return {"state": "error", "path": str(path),
            "error": "引擎正被其它进程同时改写，重试 {} 次仍未成功".format(MAX_ATTEMPTS)}


def do_patch():
    cfg = load_config()
    if not cfg.get("patchEnabled", True):
        return
    res = apply_patch(cfg)
    if res.get("error"):
        log_err("zcode-adb-patch: 引擎补丁未应用：{}".format(res["error"]))


def do_config(args):
    try:
        if args:
            if len(args) != 2:
                raise ValueError("未知参数 {}".format(" ".join(args)))
            key, val = args[0], args[1].lower()
            if key == "--patch" and val in ("on", "off"):
                save_user_config({"patchEnabled": val == "on"})
            elif key == "--auto-update" and val in ("on", "off"):
                save_user_config({"autoUpdate": val == "on"})
            else:
                raise ValueError("未知参数 {}".format(" ".join(args)))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc),
                          "usage": "config [--patch on|off] [--auto-update on|off]"}, ensure_ascii=False))
        return 2
    cfg = load_config()
    print(json.dumps({"configPath": str(user_config_path()), "engine": status(cfg),
                      "autoUpdate": cfg["autoUpdate"],
                      "autoUpdateIntervalMinutes": cfg["autoUpdateIntervalMinutes"]},
                     ensure_ascii=False))
    return 0


# ---------- 入口 ----------

def drain_stdin(timeout_s=2.0):
    """消费 stdin（hook 协议要求），设超时兜底：客户端不给 EOF 也不挂起。内容不使用。
    返回读取线程；到超时仍阻塞在 stdin 上时，退出前要走 finish_hook。"""
    def pump():
        try:
            while sys.stdin.buffer.read(65536):
                pass
        except Exception:
            pass
    t = threading.Thread(target=pump, daemon=True)
    t.start()
    t.join(timeout_s)
    return t


def finish_hook(reader):
    """hook 模式的收尾。读取线程若还阻塞在 stdin 上，不能走正常的解释器退出：Windows 上会以
    Fatal Python error（_enter_buffered_busy）崩溃、退出码 0xC0000005。此时该做的都已做完，
    刷完诊断信息后直接退出。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    if reader is not None and reader.is_alive():
        os._exit(0)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    argv = sys.argv[1:]
    mode = argv[0] if argv and not argv[0].startswith("-") else "patch"
    args = [] if mode == "patch" else argv[1:]
    reader = None
    try:
        if mode == "config":
            return do_config(args)
        if mode == "status":
            print(json.dumps(status(load_config()), ensure_ascii=False))
            return 0
        if mode == "restore":
            save_user_config({"patchEnabled": False})
            print(json.dumps(restore_engine(load_config()), ensure_ascii=False))
            return 0
        if mode == "patch":   # hook 模式：标准输出必须为空，任何异常都不外泄
            reader = drain_stdin()
            record_run(mode)
            do_patch()
        elif mode == "self-update":   # hook 模式：同上，经宿主官方 CLI 检查并安装插件更新
            reader = drain_stdin()
            record_run(mode)
            do_self_update("--force" in args)
    except Exception as exc:
        try:
            if mode in ("patch", "self-update"):
                log_err("zcode-adb-patch error: {!r}".format(exc))
            else:
                print(json.dumps({"state": "error", "error": repr(exc)}, ensure_ascii=False))
        except Exception:
            pass
    if mode in ("patch", "self-update"):
        finish_hook(reader)
    return 0


if __name__ == "__main__":
    sys.exit(main())
