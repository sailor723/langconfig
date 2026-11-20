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
