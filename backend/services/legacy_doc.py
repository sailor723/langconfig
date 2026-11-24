"""老版 Office 文件(.doc / .ppt / .xls)转纯文本 —— 一份实现,三处消费者。

为什么单独成模块:客户端发来的职务说明书里有 6 份是老 `.doc`,而平台有三处要读文件内容
(聊天上传、`read_any_file`、talent 的 JD 抽取脚本)。三处各写一份转换链的结果是:
**一处支持、另两处报"不支持"** —— 这就是用户上传 .doc 后 agent 说"找不到"的原因:
文件根本没被复制进它的工作区,而复制白名单里只有 `.docx`。

这条链是本机实际有的东西,按顺序试,并把"是谁转的"一起返回 —— 出了问题要看得出走的哪条路:

    antiword → catdoc → textutil(macOS) → libreoffice/soffice

全都不可用时返回空串和 `none`。**调用方必须处理这个返回值**,不要当成"文件是空的"。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess

#: 老格式。.docx/.pptx/.xlsx 走 python 库,不在这里。
LEGACY_EXTS = (".doc", ".ppt", ".xls")

#: 试的顺序。前两个能直接输出到 stdout,后两个要落盘中转。
_CHAIN = ("antiword", "catdoc", "textutil", "libreoffice", "soffice")


def converter_available() -> str:
    """返回第一个可用的转换器名,都没有则 'none'。给报错文案和自检用。"""
    for name in _CHAIN:
        if shutil.which(name):
            return name
    return "none"


def legacy_to_text(path: pathlib.Path, *, timeout: int = 120) -> tuple[str, str]:
    """把老格式文件转成纯文本。返回 `(text, converter)`;转不出来时 `("", "none")`。

    `path` 必须是真实文件 —— 这几个转换器都只吃路径。
    """
    path = pathlib.Path(path)
    if not path.is_file():
        return "", "none"

    if shutil.which("antiword"):
        run = subprocess.run(["antiword", str(path)], capture_output=True, text=True,
                             timeout=timeout)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "antiword"

    if shutil.which("catdoc"):
        run = subprocess.run(["catdoc", str(path)], capture_output=True, text=True,
                             timeout=timeout)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "catdoc"

    if shutil.which("textutil"):          # macOS 自带
        run = subprocess.run(["textutil", "-convert", "txt", "-stdout", str(path)],
                             capture_output=True, text=True, timeout=timeout)
        if run.returncode == 0 and run.stdout.strip():
            return run.stdout, "textutil"

    for exe in ("libreoffice", "soffice"):
        if not shutil.which(exe):
            continue
        outdir = pathlib.Path(str(path) + ".conv")
        outdir.mkdir(exist_ok=True)
        try:
            subprocess.run([exe, "--headless", "--convert-to", "txt:Text",
                            "--outdir", str(outdir), str(path)],
                           capture_output=True, timeout=max(timeout, 300))
            produced = list(outdir.glob("*.txt"))
            if produced:
                return produced[0].read_text(encoding="utf-8", errors="replace"), exe
        finally:
            shutil.rmtree(outdir, ignore_errors=True)

    return "", "none"


def unsupported_hint(suffix: str) -> str:
    """转不出来时给人看的一句话 —— 要能直接照做,不是一句"失败"。"""
    have = converter_available()
    if have == "none":
        return (f"Error: cannot read legacy {suffix} on this host — no converter found. "
                f"Install one of: antiword / catdoc / libreoffice (macOS also has textutil), "
                f"or convert the file to .docx / .txt and upload that instead.")
    return (f"Error: legacy {suffix} conversion failed even though {have} is installed — "
            f"the file may be corrupt or password-protected. "
            f"Convert it to .docx / .txt and upload that instead.")


# ── 老格式 → OOXML(给浏览器查看器)─────────────────────────────
# 为什么除了"转纯文本"还要有这条:纯文本会把版式全丢掉 —— 表格变竖排、加粗消失、
# 段落对齐没了。而"客户那份职务说明书长什么样"本身就是要看的东西,不是只要字。
#
# 转换后的文件交给**前端已有的** OfficeViewer(docx-preview)渲染,不引第二个渲染器。
# 先试 textutil(macOS)/soffice(Linux),产出标准 OOXML;都不在就返回 None,
# 调用方必须回退到纯文本 —— 返回 None 不等于"文件是空的"。

#: 转换要落盘中转,而查看器每次打开都会请求一次。不缓存就是每次重转(几秒)。
_DOCX_CACHE = pathlib.Path(__file__).resolve().parents[1] / "outputs" / ".cache" / "legacy_docx"


def legacy_to_docx(path: pathlib.Path, *, timeout: int = 120) -> pathlib.Path | None:
    """把老格式转成 OOXML,返回缓存文件路径;做不到时返回 None。

    缓存键 = (绝对路径, mtime, 大小):同一份文件重复打开不重转,文件一改自动失效。
    """
    path = pathlib.Path(path)
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix not in LEGACY_EXTS:
        return None
    target_suffix = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}[suffix]

    import hashlib

    stamp = f"{path.resolve()}|{path.stat().st_mtime_ns}|{path.stat().st_size}|{target_suffix}"
    key = hashlib.sha1(stamp.encode("utf-8")).hexdigest()[:16]
    _DOCX_CACHE.mkdir(parents=True, exist_ok=True)
    out = _DOCX_CACHE / f"{key}{target_suffix}"
    if out.is_file() and out.stat().st_size > 0:
        return out

    tmp = out.with_suffix(out.suffix + ".part")
    try:
        if shutil.which("soffice") or shutil.which("libreoffice"):
            exe = shutil.which("soffice") or shutil.which("libreoffice")
            # soffice 只能指定输出目录,文件名由它决定(同名换后缀)
            subprocess.run(
                [exe, "--headless", "--norestore", "--convert-to", target_suffix.lstrip("."),
                 "--outdir", str(_DOCX_CACHE), str(path)],
                capture_output=True, timeout=timeout, check=False,
            )
            produced = _DOCX_CACHE / f"{path.stem}{target_suffix}"
            if produced.is_file() and produced.stat().st_size > 0:
                produced.replace(tmp)
        elif shutil.which("textutil"):
            subprocess.run(
                ["textutil", "-convert", target_suffix.lstrip("."), str(path), "-output", str(tmp)],
                capture_output=True, timeout=timeout, check=False,
            )
        else:
            return None
    except (subprocess.SubprocessError, OSError):
        tmp.unlink(missing_ok=True)
        return None

    if not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return None
    tmp.replace(out)
    return out
