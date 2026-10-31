---
name: social-media
description: "\u5199\u793E\u5A92\u6587\u6848\uFF1A\u5FC5\u987B\u5148\u6D3E researcher\
  \ \u7814\u7A76\uFF0C\u4EA7\u51FA generated/social/<slug>/{post.md,card.svg}\uFF08\
  \u6587\u6848 + SVG \u914D\u56FE\uFF09\u3002\u7528\u4E8E LinkedIn\u3001X/Twitter\u3001\
  \u5C0F\u7EA2\u4E66\u3001\u516C\u4F17\u53F7\u5E16\u5B50\u6216\u628A\u957F\u6587\u6539\
  \u5199\u6210\u793E\u5A92\u3002"
version: 1.0.0
author: langconfig
tags:
- content
- writing
---

## Instructions

## 写作前必须先研究（硬性）
1. `task(subagent_type="researcher")`，描述里给主题 + 保存路径（`generated/research/<slug>.md`）；
2. 先读回报文件，再写。

## 产出契约（社媒 = 文案 + 配图，两样都算完成）
```
generated/social/<slug>/
├── post.md          # 文案（平台、正文、hashtags）
└── card.svg         # 配图（见下）
```
**没有 `card.svg` 的社媒稿视为未完成。**

## 配图怎么写（本平台没有文生图工具）
`write_file` 写一个 1080×1080 的 SVG：主色块背景 + 一句主文案（≤20 字）+ 账号名小字。
路径 `generated/social/<slug>/card.svg`，不要引用外部图片。

## 文案结构
- **平台**：先问清或判定（LinkedIn / X / 小红书 / 公众号），不同平台长短不同；
- **钩子**（第一行就要能截停）；
- 正文 3–6 行（LinkedIn 可长一些，X 控制在 280 字符内或写成串）；
- 3–5 个 hashtags；
- 事实性内容带 `[来源: URL]`。

## 自检
- [ ] `post.md` 含平台、钩子、正文、hashtags
- [ ] `card.svg` 存在
- [ ] 至少 1 处事实带来源
