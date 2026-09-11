#!/usr/bin/env python3
"""
ZCode 客户端补丁工具
=====================

对本地 ZCode 安装打两类补丁（均自动探测安装位置、独立备份、幂等）：

一、思维强度透传（内核 zcode.cjs）
  让「不在内核白名单里的模型」也遵循 config.json 里配置的思维强度档位。
  原理：内核档位解析函数把档位翻译成线上参数
  ({anthropic:{effort,thinking}} / {openaiCompatible:{reasoningEffort}})，
  但参数表 providerOptionsByLevel 只给白名单模型（claude/glm/deepseek 等家族）下发；
  自定义供应商模型拿到的是空表，档位被选中却不产生任何请求参数。
  补丁在取参处加兜底：查表为空时直接用档位名合成参数——
  白名单模型不受影响（它们的表非空，?? 短路）。

  档位 -> anthropic thinking.budget_tokens 映射：
    low=4000  medium=8000  high=16000  xhigh=32000  max=32000  其它档名=16000
    disabled/none/off/nothink -> thinking disabled

  生效条件（v2 config.json 中该模型）：
    "reasoning": { "enabled": true, "variants": ["low","high","max"], "defaultVariant": "max" }

二、用量页去截断（app.asar，--usage-chart）
  设置→用量 的趋势图只画 Top6 模型、饼图只画 Top5 并把其余合并为「其他模型」。
  补丁解析 asar 头定位渲染文件，把截断表达式替换为全量版本，
  空格补齐到原字节长度后原地覆盖（asar 头/offset/unpacked 零改动）。
  原始字节备份在 app.asar.chart-patch.json，可整体还原。

三、TPS 统计栏（app.asar，--tps-footer）
  向渲染层 out/renderer/index.html 注入 zcode-tps.js：
  输入框工具栏常驻统计胶囊 ● 时间 · 首 token · tok/s · out（当前会话最近一轮，
  切换会话即消失），数据取自页面内 MessagePort 会话事件流，无常驻服务。
  重打包级修改：整体重排 asar 目录、对改动文件重算 integrity。
  原件备份 app.asar.tps.bak，记录在 app.asar.tps-patch.json，可整体还原。

用法：
  python zcode_patcher.py                       # 思维强度补丁：自动探测全部安装并打（幂等）
  python zcode_patcher.py --check               # 只看思维强度补丁状态
  python zcode_patcher.py --revert              # 还原内核备份
  python zcode_patcher.py --extract             # 提取当前内核锚点（新版本无已知锚点时）
  python zcode_patcher.py --usage-chart         # 用量页去截断（同样支持 --check/--revert）
  python zcode_patcher.py --tps-footer          # TPS 统计栏注入（同样支持 --check/--revert）
  python zcode_patcher.py "D:\\ZCode"           # 只处理指定安装（安装根目录或 zcode.cjs 均可）

注意：ZCode 升级会覆盖 zcode.cjs 与 app.asar，升级后需重新执行对应补丁；
     打完补丁完全退出并重启 ZCode 后生效。
"""

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

# 兜底合成器：档位名 -> 各协议命名空间的线上参数
HELPER = (
    'function zCfgEffort(e){'
    'let t=String(e).toLowerCase();'
    'if(t==="disabled"||t==="none"||t==="off"||t==="nothink")'
    'return{anthropic:{thinking:{type:"disabled"}},openaiCompatible:{thinking:{type:"disabled"}}};'
    'if(t==="enabled"||t==="on")'
    'return{anthropic:{effort:"high",thinking:{type:"enabled",budgetTokens:16e3}},'
    'openaiCompatible:{thinking:{type:"enabled"}}};'
    'let r={low:4e3,medium:8e3,high:16e3,xhigh:32e3,max:32e3}[t]??16e3,'
    'o=t==="max"?"xhigh":t,'
    'n={anthropic:{thinking:{type:"enabled",budgetTokens:r}},openaiCompatible:{},openai:{}};'
    '["low","medium","high","xhigh","max"].includes(t)&&(n.anthropic.effort=t);'
    '["none","minimal","low","medium","high","xhigh"].includes(o)&&'
    '(n.openaiCompatible.reasoningEffort=o,n.openai.reasoningEffort=o);'
    'return n}'
)

MARKER = "zCfgEffort"

# 已知版本的档位解析函数原文（全文唯一锚点；符号名随构建版本变化）。
# 新版本若两版锚点都匹配不上，按文档《自定义思考等级指南》重新提取锚点后加一版。
ANCHORS = {
    "3.8.1": (
        "function sD(e,t,r){if(!e)return;let n=G_e(e,r);"
        "if(!n?.enabled||n.levels.length===0)return;"
        "let o=t?.trim(),i=Fgo(e,o,n.levels);if(o&&!i)return;"
        "let a=i??gXe(n);"
        'return a?{level:a,providerOptions:n.providerOptionsByLevel?.[a]}:void 0}'
    ),
    "3.9.1": (
        "function AD(e,t,r){if(!e)return;let n=Zye(e,r);"
        "if(!n?.enabled||n.levels.length===0)return;"
        "let o=t?.trim(),i=fxo(e,o,n.levels);if(o&&!i)return;"
        "let a=i??utt(n);"
        'return a?{level:a,providerOptions:n.providerOptionsByLevel?.[a]}:void 0}'
    ),
    "3.9.2": (
        "function RD(e,t,r){if(!e)return;let n=Xye(e,r);"
        "if(!n?.enabled||n.levels.length===0)return;"
        "let o=t?.trim(),i=Sxo(e,o,n.levels);if(o&&!i)return;"
        "let a=i??ptt(n);"
        'return a?{level:a,providerOptions:n.providerOptionsByLevel?.[a]}:void 0}'
    ),
    "3.11.2": (
        "function mN(e,t,r){if(!e)return;let n=k2e(e,r);"
        "if(!n?.enabled||n.levels.length===0)return;"
        "let o=t?.trim(),i=CIo(e,o,n.levels);if(o&&!i)return;"
        "let s=i??_nt(n);"
        'return s?{level:s,providerOptions:n.providerOptionsByLevel?.[s]}:void 0}'
    ),
}


def replacement_for(anchor: str) -> str:
    """锚点函数前插入兜底合成器，返回处在查表后追加 ?? 兜底。
    兼容不同版本的局部变量名（3.8.1/3.9.1 用 a，3.11.2 用 s）。"""
    m = re.search(r"return (\w+)\?\{level:\1,providerOptions:n\.providerOptionsByLevel\?\.\[\1\]\}", anchor)
    if not m:
        raise ValueError(f"锚点返回表达式形态未识别：{anchor[-160:]}")
    var = m.group(1)
    patched_return = (
        f"return {var}?{{level:{var},"
        f"providerOptions:n.providerOptionsByLevel?.[{var}]??zCfgEffort({var})}}:void 0}}"
    )
    head = anchor[:m.start()]
    return HELPER + head + patched_return


# ---------------------------------------------------------------- 锚点自动提取

def extract_anchor(target: Path) -> str | None:
    """
    按结构特征（而非符号名）在内核中定位档位解析函数，返回可直接加入 ANCHORS 的锚点。
    特征：函数以 {level:...,providerOptions:...providerOptionsByLevel?.[...]}:void 0} 收尾。
    已打补丁的文件自动回退到 .bak 原始件提取。
    """
    bak = target.with_suffix(".cjs.bak")
    try:
        data = target.read_text(encoding="utf-8", errors="surrogatepass")
    except PermissionError:
        print(f"[!] 无权限读取 {target}")
        return None
    if MARKER in data and bak.is_file():
        data = bak.read_text(encoding="utf-8", errors="surrogatepass")
        print(f"[*] 当前文件已打补丁，改从原始备份提取锚点")

    candidates = set()
    start = 0
    while True:
        idx = data.find("providerOptionsByLevel?.[", start)
        if idx == -1:
            break
        start = idx + 1
        fstart = data.rfind("function ", 0, idx)
        if fstart == -1:
            continue
        brace = data.find("{", fstart)
        depth, j = 0, brace
        while j < len(data):
            if data[j] == "{":
                depth += 1
            elif data[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        cand = data[fstart:j + 1]
        if "{level:" in cand and cand.endswith("}:void 0}") and "function " not in cand[len("function "):]:
            candidates.add(cand.replace("??zCfgEffort(a)", ""))

    if not candidates:
        print("[!] 未找到符合结构特征的候选，目标函数形态可能已变，需人工分析")
        return None
    if len(candidates) > 1:
        print(f"[!] 找到 {len(candidates)} 个候选（应为 1），请人工甄别：")
        for c in candidates:
            print("    -", c[:150])
        return None
    return candidates.pop()


# ---------------------------------------------------------------- 安装位置探测

def _norm(s: str) -> str:
    return s.lower().replace(" ", "").replace("-", "")


def _from_running_processes(found: list[Path]) -> None:
    """1) 正在运行的 ZCode 进程路径（最准：用户实际在用哪个）"""
    if os.name != "nt":
        return
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Where-Object {$_.Path} | "
             "Select-Object -ExpandProperty Path -Unique"],
            capture_output=True, timeout=15, errors="replace",
        ).stdout or b""
    except Exception:
        return
    for line in out.decode(errors="replace").splitlines():
        line = line.strip()
        # ZCode.exe / ZCode Skin Manager 等都指向安装根目录
        if line.lower().endswith(".exe") and "zcode" in _norm(Path(line).name):
            found.append(Path(line).parent)


def _from_registry(found: list[Path]) -> None:
    """2) 注册表卸载信息里的 InstallLocation / DisplayIcon"""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for sub in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                base = winreg.OpenKey(hive, sub)
            except OSError:
                continue
            with base:
                for i in range(winreg.QueryInfoKey(base)[0]):
                    try:
                        with winreg.OpenKey(base, winreg.EnumKey(base, i)) as k:
                            try:
                                name = winreg.QueryValueEx(k, "DisplayName")[0]
                            except OSError:
                                continue
                            if "zcode" not in _norm(str(name)):
                                continue
                            for val in ("InstallLocation", "DisplayIcon", "UninstallString"):
                                try:
                                    v = str(winreg.QueryValueEx(k, val)[0])
                                except OSError:
                                    continue
                                p = Path(v.strip('"').split(",")[0].strip())
                                found.append(p if p.is_dir() else p.parent)
                                break
                    except OSError:
                        continue


def _from_common_dirs(found: list[Path]) -> None:
    """3) 常规安装目录：Windows Program Files 系 / macOS /Applications / Linux /opt、/usr/share"""
    bases = [os.environ.get("ProgramFiles"),
             os.environ.get("ProgramFiles(x86)"),
             os.environ.get("ProgramW6432"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
             "/Applications",
             os.path.expanduser("~/Applications"),
             "/opt",
             "/usr/share"]
    for base in bases:
        if not base or not Path(base).is_dir():
            continue
        try:
            for entry in os.scandir(base):
                if not entry.is_dir() or "zcode" not in _norm(entry.name):
                    continue
                if entry.name.endswith(".app"):
                    found.append(Path(entry.path) / "Contents")   # macOS .app 包，资源在 Contents 下
                else:
                    found.append(Path(entry.path))
        except OSError:
            continue


def discover() -> list[Path]:
    """返回所有探测到的 zcode.cjs（去重、保序）"""
    roots: list[Path] = []
    for probe in (_from_running_processes, _from_registry, _from_common_dirs):
        try:
            probe(roots)
        except Exception:
            pass
    seen, result = set(), []
    for root in roots:
        cjs = root / "resources" / "glm" / "zcode.cjs"
        try:
            key = cjs.resolve()
        except OSError:
            key = cjs
        if cjs.is_file() and key not in seen:
            seen.add(key)
            result.append(cjs)
    return result


def resolve_target(arg: str | None) -> list[Path]:
    if not arg:
        return discover()
    p = Path(arg)
    # 显式路径兼容多种形态：安装根目录 / macOS 的 .app 包 / zcode.cjs 文件本身
    roots = [p, p / "Contents"] if p.name.lower().endswith(".app") else [p]
    for root in roots:
        cjs = root / "resources" / "glm" / "zcode.cjs"
        if cjs.is_file():
            return [cjs]
    raise SystemExit(f"[!] 指定路径下找不到 zcode.cjs：{arg}")


# ---------------------------------------------------------------- 单个目标处理

def process(target: Path, check_only: bool, revert: bool) -> None:
    backup = target.with_suffix(".cjs.bak")
    try:
        data = target.read_text(encoding="utf-8", errors="surrogatepass")
    except PermissionError:
        print(f"[!] 无权限读取 {target}（Program Files 需要管理员运行本脚本）")
        return

    state = "已打" if MARKER in data else ("已还原/未打" if backup.is_file() else "未打")
    print(f"[*] {target}")
    print(f"    {len(data):,} 字符 | 补丁: {state} | 备份: {'有' if backup.is_file() else '无'}")

    if revert:
        if not backup.is_file():
            print("    [.] 没有备份，跳过")
            return
        try:
            shutil.copyfile(backup, target)
            print("    [+] 已从备份还原")
        except PermissionError:
            print("    [!] 无权限写入，请用管理员身份运行本脚本")
        return

    if check_only:
        return

    if MARKER in data:
        print("    [=] 已打过补丁，跳过")
        return

    matched = [(ver, a) for ver, a in ANCHORS.items() if data.count(a) == 1]
    if len(matched) != 1:
        detail = ", ".join(f"{ver}={data.count(a)}" for ver, a in ANCHORS.items())
        print(f"    [!] 锚点匹配异常（{detail}，期望恰有一版=1），"
              f"版本可能不在已支持列表，按文档重新提取锚点后添加")
        return
    ver, anchor = matched[0]
    print(f"    [+] 匹配版本锚点: {ver}")

    try:
        if not backup.is_file():
            shutil.copyfile(target, backup)
        patched = data.replace(anchor, replacement_for(anchor))
        target.write_text(patched, encoding="utf-8", errors="surrogatepass", newline="\n")
    except PermissionError:
        print(f"    [!] 无权限写入（Program Files 需要管理员），未修改。"
              f"可用管理员身份的 PowerShell/Git Bash 重新运行本脚本")
        return

    ok = MARKER in target.read_text(encoding="utf-8", errors="surrogatepass")
    print(f"    [{'+' if ok else '!'}] 补丁{'写入成功' if ok else '写入失败'}"
          f"{'（备份 -> ' + str(backup) + '）' if backup.is_file() else ''}")


# ------------------------------------------------------- 用量页去截断补丁（asar 内同长度原地改字节）

# 每项：key=定位用的文件名特征，pattern=截断表达式原文，replacement=等价短替换（空格补齐）
USAGE_PATCHES = [
    {
        "key": "AppUsageDailyModelTrendChart",
        "pattern": b"n.models.slice(0,6)",
        "replacement": b"n.models",
        "desc": "每日趋势图：去掉 Top6 截断，全部模型出线",
    },
    {
        "key": "AppUsageModelUsagePieChart",
        "pattern": b"i=n.length>Q,a=i?Q-1:Q",
        "replacement": b"i=!1,a=1/0",
        "desc": "模型用量饼图：去掉 Top5+其他模型 合并，全部模型出块",
    },
]


def _asar_header_index(asar: Path):
    """解析 asar 头，返回 [(文件路径, 绝对偏移, 尺寸), ...]。"""
    with open(asar, "rb") as f:
        head = f.read(16)
        header_size = struct.unpack("<I", head[4:8])[0]
        json_len = struct.unpack("<I", head[12:16])[0]
        f.seek(16)
        header = json.loads(f.read(json_len).decode("utf-8"))

    def walk(node, path):
        for name, ent in (node.get("files") or {}).items():
            p = f"{path}/{name}" if path else name
            if "files" in ent:
                yield from walk(ent, p)
            else:
                yield p, ent

    data_start = 8 + header_size
    return [(p, data_start + int(e["offset"]), e["size"])
            for p, e in walk(header, "") if not e.get("unpacked")]


def _load_sidecar(side: Path, asar_size: int | None = None) -> list[dict]:
    """读取补丁记录；兼容旧的单条格式。带 asar_size 指纹校验：
    ZCode 升级会整个覆盖 app.asar，旧记录的 offset 不再可信，失配即作废。"""
    if not side.is_file():
        return []
    data = json.loads(side.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "patches" in data:
        data = data["patches"]
    elif isinstance(data, dict):
        data = [data]
    if asar_size is not None:
        data = [r for r in data if r.get("asar_size") == asar_size]
    return data


def process_usage_chart(asar: Path, check_only: bool, revert: bool) -> None:
    side = asar.with_name(asar.name + ".chart-patch.json")
    asar_size = asar.stat().st_size
    entries = _asar_header_index(asar)

    specs = []
    for item in USAGE_PATCHES:
        match = [(p, o, s) for p, o, s in entries if item["key"] in p]
        if len(match) != 1:
            print(f"[!] {asar}\n    {item['key']} 命中 {len(match)} 个文件（期望 1），该项跳过")
            continue
        specs.append((item, match[0]))

    if revert:
        saved = _load_sidecar(side, asar_size)
        if not saved:
            print(f"[.] {asar}\n    没有当前版本的 sidecar 备份，跳过")
            return
        with open(asar, "r+b") as f:
            for rec in saved:
                f.seek(rec["offset"])
                f.write(base64.b64decode(rec["original_b64"]))
        side.unlink()
        print(f"[+] {asar}\n    已还原 {len(saved)} 处原始字节")
        return

    print(f"[*] {asar}")
    saved = _load_sidecar(side, asar_size)
    changed = False
    for item, (path, off, size) in specs:
        fname = path.split("/")[-1]
        with open(asar, "r+b") as f:
            f.seek(off)
            raw = f.read(size)
        if item["pattern"] not in raw:
            print(f"    [=] {fname} | 已打（{item['desc']}）")
            continue
        cnt = raw.count(item["pattern"])
        if cnt != 1:
            print(f"    [!] {fname} | 截断表达式出现 {cnt} 次（期望 1），拒绝盲改")
            continue
        if check_only:
            print(f"    [ ] {fname} | 未打（{item['desc']}）")
            continue
        new = raw.replace(item["pattern"], item["replacement"], 1)
        padded = new + b" " * (len(raw) - len(new))   # 同长度原地覆盖，asar 头零改动
        if not any(r.get("offset") == off for r in saved):
            saved.append({
                "path": path,
                "offset": off,
                "size": size,
                "asar_size": asar_size,
                "original_b64": base64.b64encode(raw).decode(),
            })
        with open(asar, "r+b") as f:
            f.seek(off)
            f.write(padded)
            f.seek(off)
            back = f.read(size)
        ok = item["pattern"] not in back and len(back) == size
        print(f"    [{'+' if ok else '!'}] {fname} | {'写入成功（' + item['desc'] + '）' if ok else '写入失败'}")
        changed = True
    if changed and not check_only:
        side.write_text(json.dumps({"patches": saved}, ensure_ascii=False), encoding="utf-8")
        print(f"    原始字节备份: {side.name}")


# ------------------------------------------------- TPS 统计栏注入（asar 重打包级）

TPS_INDEX_PATH = "out/renderer/index.html"
TPS_SCRIPT_PATH = "out/renderer/zcode-tps.js"
TPS_TAG = f'<script src="./{TPS_SCRIPT_PATH.split("/")[-1]}"></script>'


def _asar_header_raw(asar: Path):
    """读整个 asar：返回 (原始全量 bytes, header 树, 数据区起始偏移)。"""
    raw = asar.read_bytes()
    if len(raw) < 16:
        raise ValueError(f"asar 文件过小: {asar}")
    f0, f1, f2, f3 = struct.unpack("<4I", raw[:16])
    if f0 != 4:
        raise ValueError(f"asar 头格式不符（首 uint32={f0}，期望 4）: {asar}")
    header = json.loads(raw[16:16 + f3].decode("utf-8"))
    return raw, header, 8 + f1


def _asar_entry_bytes(raw: bytes, data_start: int, ent: dict) -> bytes:
    off = data_start + int(ent["offset"])
    return raw[off:off + ent["size"]]


def _asar_integrity(data: bytes, block_size: int = 4194304) -> dict:
    blocks = [hashlib.sha256(data[i:i + block_size]).hexdigest()
              for i in range(0, len(data), block_size)]
    return {"algorithm": "SHA256", "hash": hashlib.sha256(data).hexdigest(),
            "blockSize": block_size, "blocks": blocks}


def _asar_walk_entries(node, path=""):
    """yield (全路径, 叶子条目 dict)。目录与 unpacked 条目不产出。"""
    for name, ent in (node.get("files") or {}).items():
        p = f"{path}/{name}" if path else name
        if "files" in ent:
            yield from _asar_walk_entries(ent, p)
        elif not ent.get("unpacked"):
            yield p, ent


def _repack_asar(asar: Path, overwrite: dict[str, bytes], remove: set[str]) -> int:
    """通用 asar 重打包：树中删除 remove 条目，overwrite 覆盖/新增文件数据并重算 integrity，
    全部条目 offset 重排；写临时文件、回读校验后原子替换。返回新文件大小。"""
    raw, header, data_start = _asar_header_raw(asar)

    # overwrite 中树里尚不存在的路径（新增文件）按层级插入占位条目
    for p in overwrite:
        parts = p.split("/")
        node = header
        for part in parts[:-1]:
            node = node.setdefault("files", {}).setdefault(part, {"files": {}})
        leaf = node.setdefault("files", {})
        leaf.setdefault(parts[-1], {"size": 0, "offset": "0"})

    def purge(node, prefix):
        files = node.get("files") or {}
        for name in list(files.keys()):
            ent = files[name]
            p = f"{prefix}/{name}" if prefix else name
            if "files" in ent:
                purge(ent, p)
                if not ent["files"]:
                    del files[name]          # 删空的目录一并移除
            elif p in remove:
                del files[name]

    purge(header, "")
    # relayout 会改写 ent.offset，旧数据位置必须先快照（emit 二次读数据时用）
    old_positions = {p: (int(ent["offset"]), ent["size"]) for p, ent in _asar_walk_entries(header)}
    cursor = 0

    def entry_data(p: str, ent: dict) -> bytes:
        data = overwrite.get(p)
        if data is None:
            off, size = old_positions[p]
            data = raw[data_start + off:data_start + off + size]
        return data

    def relayout(node, prefix):
        nonlocal cursor
        for name, ent in (node.get("files") or {}).items():
            p = f"{prefix}/{name}" if prefix else name
            if "files" in ent:
                relayout(ent, p)
            elif ent.get("unpacked"):
                continue
            else:
                data = entry_data(p, ent)
                ent["size"] = len(data)
                ent["offset"] = str(cursor)
                if p in overwrite:
                    ent["integrity"] = _asar_integrity(data)
                cursor += len(data)

    relayout(header, "")
    json_bytes = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = (4 - len(json_bytes) % 4) % 4
    header_blob = (struct.pack("<4I", 4, 8 + len(json_bytes) + pad, 4 + len(json_bytes) + pad, len(json_bytes))
                   + json_bytes + b"\x00" * pad)

    tmp = asar.with_name(asar.name + ".tps-tmp")
    with open(tmp, "wb") as out:
        out.write(header_blob)

        def emit(node, prefix):
            for name, ent in (node.get("files") or {}).items():
                p = f"{prefix}/{name}" if prefix else name
                if "files" in ent:
                    emit(ent, p)
                elif ent.get("unpacked"):
                    continue
                else:
                    out.write(entry_data(p, ent))

        emit(header, "")

    v_raw, v_header, v_start = _asar_header_raw(tmp)
    v_files = dict(_asar_walk_entries(v_header))
    try:
        for p, want in overwrite.items():
            ent = v_files.get(p)
            if ent is None or _asar_entry_bytes(v_raw, v_start, ent) != want:
                raise ValueError(f"重打包校验失败: {p}")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, asar)
    return asar.stat().st_size


def _refresh_chart_sidecar(asar: Path) -> None:
    """asar 重打包后数据区整体位移，chart 补丁记录里的绝对 offset 与 asar_size 指纹需重定位。"""
    side = asar.with_name(asar.name + ".chart-patch.json")
    if not side.is_file():
        return
    try:
        recs = json.loads(side.read_text(encoding="utf-8")).get("patches", [])
    except Exception:
        return
    if not recs:
        return
    entries = {p: (o, s) for p, o, s in _asar_header_index(asar)}
    cur_size = asar.stat().st_size
    changed = False
    for r in recs:
        hit = entries.get(r.get("path"))
        if hit and hit[1] == r.get("size") and (r.get("offset") != hit[0] or r.get("asar_size") != cur_size):
            r["offset"], r["asar_size"] = hit[0], cur_size
            changed = True
    if changed:
        side.write_text(json.dumps({"patches": recs}, ensure_ascii=False), encoding="utf-8")
        print(f"[*] 已同步 {side.name} 的 offset/指纹到重打包后的 asar")


def process_tps_footer(asar: Path, check_only: bool, revert: bool, tps_src: Path | None) -> None:
    side = asar.with_name(asar.name + ".tps-patch.json")
    bak = asar.with_name(asar.name + ".tps.bak")
    asar_size = asar.stat().st_size

    raw, header, data_start = _asar_header_raw(asar)
    paths = {p: ent for p, ent in _asar_walk_entries(header)}
    idx_ent = paths.get(TPS_INDEX_PATH)
    if idx_ent is None:
        print(f"[!] {asar}\n    未找到 {TPS_INDEX_PATH}，版本结构可能已变，跳过")
        return
    idx_bytes = _asar_entry_bytes(raw, data_start, idx_ent)
    tagged = TPS_TAG.encode() in idx_bytes
    installed = tagged and TPS_SCRIPT_PATH in paths

    saved = None
    if side.is_file():
        try:
            rec = json.loads(side.read_text(encoding="utf-8"))
            if rec.get("asar_size") == asar_size:
                saved = rec
        except Exception:
            saved = None

    if check_only:
        state = "已打" if installed else ("不完整（index.html 有 tag 但缺脚本条目）" if tagged else "未打")
        print(f"[*] {asar}\n    TPS 统计栏注入: {state} | sidecar: {'有' if saved else '无'} | 备份: {'有' if bak.is_file() else '无'}")
        return

    if revert:
        if not installed and not saved:
            print(f"[.] {asar}\n    未打 TPS 注入，跳过")
            return
        if saved and saved.get("index_original_b64"):
            original_idx = base64.b64decode(saved["index_original_b64"])
        else:
            original_idx = idx_bytes.replace(TPS_TAG.encode(), b"")
        new_size = _repack_asar(asar, {TPS_INDEX_PATH: original_idx}, {TPS_SCRIPT_PATH})
        side.unlink(missing_ok=True)
        bak.unlink(missing_ok=True)
        _refresh_chart_sidecar(asar)
        print(f"[+] {asar}\n    已还原 index.html 并移除 {TPS_SCRIPT_PATH}（新大小 {new_size:,} 字节，备份已清理）")
        return

    if installed:
        print(f"[=] {asar}\n    已打 TPS 注入，跳过")
        return
    if idx_bytes.count(b"</body>") != 1:
        print(f"[!] {asar}\n    index.html 的 </body> 出现 {idx_bytes.count(b'</body>')} 次（期望 1），拒绝盲改")
        return
    if tps_src is None:
        tps_src = Path(__file__).resolve().parent / "zcode-tps.js"
    if not tps_src.is_file():
        raise SystemExit(f"[!] 找不到注入源脚本 {tps_src}（可用 --tps-src 指定路径）")
    script_bytes = tps_src.read_bytes()

    if not bak.is_file():
        shutil.copyfile(asar, bak)

    new_idx = idx_bytes.replace(b"</body>", TPS_TAG.encode() + b"</body>", 1)
    new_size = _repack_asar(asar, {TPS_INDEX_PATH: new_idx, TPS_SCRIPT_PATH: script_bytes}, set())
    side.write_text(json.dumps({
        "asar_size": new_size,
        "index_path": TPS_INDEX_PATH,
        "script_entry": TPS_SCRIPT_PATH,
        "index_original_b64": base64.b64encode(idx_bytes).decode(),
    }, ensure_ascii=False), encoding="utf-8")
    _refresh_chart_sidecar(asar)
    print(f"[+] {asar}\n    TPS 统计栏注入完成（{tps_src.name} {len(script_bytes):,} 字节 -> {TPS_SCRIPT_PATH}，index.html 已挂载）\n"
          f"    原件备份: {bak.name} | 记录: {side.name}")


def _resolve_asars(target: str | None) -> list[Path]:
    asars = []
    for cjs in resolve_target(target):
        asar = cjs.parent.parent / "app.asar"   # resources/glm/zcode.cjs -> resources/app.asar
        if asar.is_file() and asar not in asars:
            asars.append(asar)
    if not asars:
        raise SystemExit("[!] 未找到 app.asar")
    return asars


def main() -> None:
    ap = argparse.ArgumentParser(description="ZCode 客户端补丁工具：思维强度透传 + 用量页去截断 + TPS 统计栏（自动探测安装位置）")
    ap.add_argument("target", nargs="?", help="可选：安装根目录或 zcode.cjs 路径；缺省自动探测全部")
    ap.add_argument("--check", action="store_true", help="只检查状态，不修改")
    ap.add_argument("--revert", action="store_true", help="从备份还原")
    ap.add_argument("--extract", action="store_true",
                    help="按结构特征提取当前内核的档位解析函数锚点（新版本升级后用）")
    ap.add_argument("--usage-chart", action="store_true",
                    help="补丁用量页：去掉趋势图 Top6 与饼图 Top5+其他模型 的截断，全部模型展示")
    ap.add_argument("--tps-footer", action="store_true",
                    help="注入 TPS 统计栏：输入框工具栏常驻胶囊（● 时间 · 首 token · tok/s · out），asar 重打包级")
    ap.add_argument("--tps-src", default=None,
                    help="指定注入的 zcode-tps.js 路径（默认用本脚本同目录自带的）")
    args = ap.parse_args()

    if args.usage_chart or args.tps_footer:
        asars = _resolve_asars(args.target)
        if args.usage_chart:
            mode = "检查" if args.check else ("还原" if args.revert else "打补丁")
            print(f"=== 用量页去截断补丁，目标 {len(asars)} 处，模式：{mode} ===")
            for a in asars:
                process_usage_chart(a, args.check, args.revert)
        if args.tps_footer:
            mode = "检查" if args.check else ("还原" if args.revert else "打补丁")
            print(f"=== TPS 统计栏注入，目标 {len(asars)} 处，模式：{mode} ===")
            src = Path(args.tps_src) if args.tps_src else None
            for a in asars:
                try:
                    process_tps_footer(a, args.check, args.revert, src)
                except PermissionError:
                    print(f"[!] {a}\n    文件被占用（ZCode 正在运行）或无写入权限；完全退出 ZCode 后重试")
        if not args.check and not args.revert:
            print("=== 提示：完全退出并重启 ZCode 后生效；升级后需重新执行 ===")
        return

    targets = resolve_target(args.target)
    if not targets:
        raise SystemExit("[!] 未探测到任何 ZCode 安装；请把安装目录路径作为参数传入")

    if args.extract:
        for t in targets:
            print(f"[*] {t}")
            anchor = extract_anchor(t)
            if anchor:
                print("[+] 提取成功，把下面整段加入脚本 ANCHORS 后重新运行打补丁：\n")
                print(f'    "<版本号>": (\n        {anchor!r}\n    ),')
        return

    mode = "检查" if args.check else ("还原" if args.revert else "打补丁")
    print(f"=== 探测到 {len(targets)} 处安装，模式：{mode} ===")
    for t in targets:
        process(t, args.check, args.revert)

    if not args.check and not args.revert:
        print("=== 提示：完全退出并重启 ZCode 后生效；升级后需重新执行本脚本 ===")


if __name__ == "__main__":
    main()
