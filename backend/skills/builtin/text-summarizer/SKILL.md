---
name: Text Summarizer（文本摘要器）
description: 把长文本概括为简洁的要点列表。
version: 1.0.0
author: AI Generated
tags:
- summarization
- text-processing
triggers:
- 当用户要求总结文本时
lang: zh
translated: machine
source: backend/skills/en-originals/text-summarizer/SKILL.md
---

## Instructions（指令）

1. 使用 read_file 工具读取输入文本。如果文本已在对话中直接给出，就直接往下做。
2. 找出文本中的关键点、主旨以及重要的支撑细节。
3. 生成一份简洁的摘要，以要点列表的形式呈现，只保留最核心的信息。
