"""Append python_execute run instructions to agent 162's system prompt."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from dotenv import load_dotenv

load_dotenv(os.path.join("..", ".env"))

from db.database import SessionLocal
from models.deep_agent import DeepAgentTemplate

NEW_SECTION = """
## 九、使用 python_execute 运行 PPTX 脚本
- 生成 `generate_pptx.py` 后，必须用 **python_execute** 工具直接运行该脚本，产出 .pptx 文件，不得让用户手动运行。
- 调用方式（注意 python_execute 的工作目录是 backend 目录，必须先 chdir 到脚本所在目录，且用绝对路径）：
  python_execute(code="import os; os.chdir(r'<脚本所在目录绝对路径>'); exec(open(r'<脚本绝对路径>').read())")
- 运行成功后，读取生成的 .pptx 文件信息（文件名、页数），并在交付清单中列出。
"""

db = SessionLocal()
try:
    row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == 162).first()
    if not row:
        print("AGENT 162 NOT FOUND")
        sys.exit(1)

    cfg = copy.deepcopy(row.config)
    sp = cfg.get("system_prompt", "")

    if "python_execute" in sp:
        print("Section 九 already present — skipping append")
    else:
        sp = sp.rstrip() + NEW_SECTION
        cfg["system_prompt"] = sp
        # JSON column: must reassign, not mutate in place
        row.config = cfg
        db.commit()
        print("APPENDED. new prompt length:", len(sp))
finally:
    db.close()
