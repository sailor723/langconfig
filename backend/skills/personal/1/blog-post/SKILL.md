---
name: blog-post
description: "\u5199\u957F\u6587\u535A\u5BA2\uFF1A\u5FC5\u987B\u5148\u6D3E researcher\
  \ \u7814\u7A76\uFF0C\u4EA7\u51FA generated/blogs/<slug>/{post.md,hero.svg}\uFF08\
  \u6B63\u6587 + SVG \u5C01\u9762\uFF09\u3002\u7528\u4E8E\u5199\u535A\u5BA2\u3001\u6559\
  \u7A0B\u3001how-to\u3001\u6280\u672F\u957F\u6587\u3001thought leadership\u3002"
version: 1.0.0
author: langconfig
tags:
- content
- writing
---

## Instructions

## 写作前必须先研究（硬性）
1. 调用 `task(subagent_type="researcher")`，任务描述里**同时给主题和保存路径**：
   `研究<主题>，把结果写到 generated/research/<slug>.md，必须带来源 URL`
2. 收到回报后先读那个文件，再动笔。

## 产出契约（博客 = 正文 + 封面，两样都算完成）
```
generated/blogs/<slug>/
├── post.md          # 正文
└── hero.svg         # 封面（见下）
```
- slug：小写、连字符，从标题派生（例：`ai-agents-2025`）。
- **没有 `hero.svg` 的博客视为未完成。**

## 封面怎么写（本平台没有文生图工具）
用 `write_file` 写一个 1200×630 的 SVG，包含：
- 深色背景（`#0B1220`）+ 一条主题色装饰（`#4F8CFF`）；
- 主标题（≤14 字，可换行）、副标题（一句话）；
- 右下角小字：`<品牌名> · <日期>`。
文件写到 `generated/blogs/<slug>/hero.svg`，**不要**引用外部图片。

## 正文结构
1. **钩子**（3 行内说清读者能得到什么）
2. `## ` 分节 3–6 个，每节一个观点，配具体例子/数字
3. 需要时给代码块（标明语言）
4. `## 结论 / 下一步`（明确 CTA）
5. 全文 1200–2000 字；段落 ≤4 行

## 自检（完成前逐条过）
- [ ] `post.md` 存在，含钩子 + 3–6 个 H2 + CTA
- [ ] `hero.svg` 存在且能被浏览器打开
- [ ] 至少 3 处事实来自研究文件，并带 `[来源: URL]`
