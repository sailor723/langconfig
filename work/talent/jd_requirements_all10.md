# 全部 10 份 JD 的要求清单 · 按 8 维分类

> 范围:**10 份职务说明书的任职资格段**,逐句拆成原子要求,按 `dimension` 归类。
> 依据:JD 原文(逐字)。**这不是标准补充** —— 标准补充的项单列在末尾。
>
> 8 维:`A` 人口属性 · `B` 教育 · `C` 经历 · `D` 技能 · `E` 素质能力 · `F` 资质证书 · `G` 合规 · `H` 语言

---

## 一、逐份清单

### 1 · 品质经理(9 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 年龄：25 ~ 40岁 | **A** age | range | ✅ |
2 | 学历：大专及以上 | **B** level | ordinal | ✅ |
3 | 专业：机电一体化/电子技术/自动化/工业工程/机械工程等工程类专业**毕业** | **B** major | binary | ✅需 major |
4 | 语言：英语口语熟练及具备独立书写英文8D报告的能力 | **H** | level+binary | ✅需 languageLevel |
5 | 3年以上品质管理工作经验 | **C** years+domain | composite | ✅ |
6 | 熟识线束行业相关产品 | **C** industry / **D** domain | binary | 🟡 |
7 | 具备品质问题分析、改善的能力 | **D** capability | binary | ✅ |
8 | 懂QC七大手法、5WHY、SPC、CPK、6S工具 | **D** composite×5 | composite | ✅ |
9 | 具备接待客户验厂经验 | **C** experience | binary | ✅ |
10 | 有良好的沟通、协调能力 | **E** behavioral | soft | ❌ |
→ A1 B2 C3 D3 E1 H1 = **11**

### 2 · 业务跟单(9 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 学历：高中及以上 | **B** level | ordinal | ✅ |
2 | 国际贸易、商务管理类相关专业**优先** | **B** major | desirable | ✅需 major |
3 | 经验：2年以上制造业订单跟单经验 | **C** years+domain+industry | composite | ✅ |
4 | 熟悉ERP系统操作 | **D** product | binary | ✅ |
5 | 熟练使用ERP订单管理模块及Excel数据分析 | **D** composite×2 | composite | ✅ |
6 | 具备订单交期风险评估能力 | **D** capability | binary | ✅ |
7 | 抗压能力强,可同时处理多线程任务 | **E** behavioral | soft | ❌ |
8 | 沟通协调能力佳,能独立对接客户与生产部门 | **E** behavioral | soft | ❌ |
9 | 合规：严守数据保密制度,无客户信息泄露记录 | **G** corporate | binary | 🟡 |
→ B2 C1 D3 E2 G1 = **9**

### 3 · 副总助理(16 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 基本要求：**女性** | **A** gender | binary | ✅需 gender |
2 | **25-38岁** | **A** age | range | ✅ |
3 | **全日制**大专及以上 | **B** level+fullTime | ordinal | ✅需 fullTime |
4 | 中文、文秘类专业**优先** | **B** major | desirable | ✅需 major |
5 | 2年以上文职类、助理类、管理类工厂工作经验 | **C** years+domain+industry | composite | ✅ |
6 | 熟练掌握Office办公软件（Word/ Excel/ PPT/ AI） | **D** composite×4 | composite | ✅ |
7 | 原则性强 | **E** behavioral | soft | ❌ |
8 | 责任心突出 | **E** behavioral | soft | ❌ |
9 | 敢于担当 | **E** behavioral | soft | ❌ |
10 | 坚持日清日结 | **E** behavioral | soft | ❌ |
11 | 具备良好的奋斗精神 | **E** motivational | soft | ❌ |
12 | 沟通能力好 | **E** behavioral | soft | ❌ |
13 | 执行能力强 | **E** behavioral | soft | ❌ |
14 | 逻辑清晰 | **E** cognitive | soft | ❌ |
15 | 数据敏感 | **E** cognitive | soft | ❌ |
16 | (隐含)全日制 vs 非全日制 | **B** fullTime | binary | ✅需 fullTime |
→ A2 B3 C1 D1 E9 = **16**

### 4 · 业务助理(12 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | **女性** | **A** gender | binary | ✅需 gender |
2 | 年龄**20-30岁** | **A** age | range | ✅ |
3 | 高中以上学历 | **B** level | ordinal | ✅ |
4 | 市场营销、外语外贸、销售等专业者**优先考虑** | **B** major | desirable | ✅需 major |
5 | 2年以上业务助理或相关工作经验 | **C** years+domain | composite | ✅ |
6 | **同行业者优先考虑** | **C** industry | desirable | 🟡 |
7 | 熟悉使用Office办公软件 | **D** composite×3 | composite | ✅ |
8 | 性格开朗 | **E** behavioral | soft | ❌ |
9 | 具备基本商务礼仪知识 | **E** knowledge | soft | ❌ |
10 | 有业务发展意向 | **E** motivational | soft | ❌ |
11 | 具备良好的沟通协调能力和团队合作精神 | **E** behavioral | soft | ❌ |
12 | 能吃苦耐劳,责任心强,对工作有积极主动性 | **E** behavioral | soft | ❌ |
→ A2 B2 C2 D1 E5 = **12**

### 5 · 专案工程师(5 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 电线连接器加工行业产品开发3年以上经验 | **C** years+industry | composite | ✅ |
2 | 对新产品报价、样品、转量产做业流程熟知 | **D** domain | binary | 🟡 |
3 | 抗压能力强,积极向上,工作细心,谨慎 | **E** behavioral | soft | ❌ |
4 | 对电线加工设备：裁线机、端子机、自动机、注塑机、点胶机等功能熟知并有一定的操作能力 | **D** equipment×5 | composite | ✅ |
5 | CAD二维制图、办公软件操作熟练 | **D** composite×2 | composite | ✅ |
→ C1 D3 E1 = **5**

### 6 · 人资专员(7 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 高中及以上学历,专业不限 | **B** level | ordinal | ✅ |
2 | 行政、文秘类**优先** | **B** major | desirable | ✅需 major |
3 | 熟练使用办公软件以及考勤系统 | **D** composite | composite | ✅ |
4 | 熟悉国家相关法律政策,熟悉社会保险（增/减/补缴）等操作流程 | **D** domain | binary | ✅ |
5 | 具备很好的数据统计分析能力 | **D** capability | binary | ✅ |
6 | 具有人事数据保密意识 | **G** corporate | soft | ❌ |
7 | 跨部门沟通能力,工作认真,具有责任心 | **E** behavioral | soft | ❌ |
→ B2 D3 E1 G1 = **7**

### 7 · 关务报关员(8 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 年龄**25-45岁** | **A** age | range | ✅ |
2 | 大专及以上学历 | **B** level | ordinal | ✅ |
3 | (国际贸易、物流专业**优先**) | **B** major | desirable | ✅需 major |
4 | 熟悉进出口报关流程 | **D** domain | binary | ✅ |
5 | **5年以上**关务操作经验 | **C** years | ordinal | ✅ |
6 | 通过基础**贸易安全合规培训考核** | **F** training | binary | 🟡需 certification |
7 | **无海关行政处罚、犯罪记录** | **G** legal | binary | 🟡 |
8 | 对数据细心敏感,执行力、沟通能力、日报/周报/月报整理能力、事毕、职业道德、团队合作、主动性、责任感 | **E** behavioral×9 | soft | ❌ |
9 | 熟练掌握Office办公软件基本操作 | **D** composite | composite | ✅ |
→ A1 B2 C1 D2 E1 F1 G1 = **9**

### 8 · 工程文员(6 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 高中及以上学历 | **B** level | ordinal | ✅ |
2 | 熟练：Excel、Word、ppt等办公软件,同时具备**AI工具**的基本运用能力 | **D** composite×4 | composite | ✅ |
3 | 有同等岗位工作经验**二年以上** | **C** years | ordinal | ✅ |
4 | 能识别图纸基本信息：线材规格、端子型号、胶壳料号、回路标识等 | **D** domain | composite | ✅ |
5 | 善于沟通,责任心与进取心强,工作认真、严谨细致 | **E** behavioral | soft | ❌ |
→ B1 C1 D2 E1 = **6**（D 内含 AI,与副总助理一致）

### 9 · 招聘专员(9 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 中专以上学历 | **B** level | ordinal | ✅ |
2 | **1年以上**招聘工作经验 | **C** years | ordinal | ✅ |
3 | 良好的沟通表达协调能力强、准确、清晰、责任心强、细心、稳重 | **E** behavioral×6 | soft | ❌ |
4 | 熟练使用相关办公软件 | **D** composite | composite | ✅ |
5 | 具备基本的**招聘技巧** | **D** capability | binary | ✅ |
6 | 熟悉通常的**招聘渠道** | **D** domain | binary | ✅ |
7 | 独立工作能力强 | **E** behavioral | soft | ❌ |
8 | 丰富的招聘经验 | **C** experience | soft | ❌ |
9 | 对招聘工作感兴趣 | **E** motivational | soft | ❌ |
10 | 熟悉相关招聘知识 | **D** knowledge | binary | ✅ |
→ B1 C2 D4 E3 = **10**

### 10 · 管理课长(11 条)

| # | 原文 | dim | kind | 可判 |
|---|---|---|---|---|
1 | 性别要求：**男女不限** | **A** gender | none(显式无约束) | — |
2 | 年龄要求：**30岁—45岁** | **A** age | range | ✅ |
3 | 专业要求：人力资源管理、行政管理、法律、企业管理等相关专业 | **B** major(**required**) | binary | ✅需 major |
4 | 学历要求：大专或以上 | **B** level | ordinal | ✅ |
5 | 技能要求：熟悉OFFICE软件、办公室网络 | **D** composite | composite | ✅ |
6 | 能力要求：**数据分析**能力 | **D** capability | binary | ✅ |
7 | 能力要求：**培训课程开发**能力 | **D** capability | binary | ✅ |
8 | 能力要求：**体系管理**能力 | **D** capability | binary | ✅ |
9 | 能力要求：**系统规划**能力 | **D** capability | binary | ✅ |
10 | 能力要求：**企业文化建设**能力 | **D** capability | binary | ✅ |
11 | 经验要求：相关经验**5年以上** | **C** years | ordinal | ✅ |
→ A2 B2 C1 D6 = **11**

---

## 二、矩阵:10 份 JD × 8 维

| JD | A 人口 | B 教育 | C 经历 | D 技能 | E 素质 | F 资质 | G 合规 | H 语言 | 合计 |
|---|---|---|---|---|---|---|---|---|---|
品质经理 | 1 | 2 | 3 | 3 | 1 | 0 | 0 | 1 | **11** |
业务跟单 | 0 | 2 | 1 | 3 | 2 | 0 | 1 | 0 | **9** |
副总助理 | 2 | 3 | 1 | 1 | 9 | 0 | 0 | 0 | **16** |
业务助理 | 2 | 2 | 2 | 1 | 5 | 0 | 0 | 0 | **12** |
专案工程师 | 0 | 0 | 1 | 3 | 1 | 0 | 0 | 0 | **5** |
人资专员 | 0 | 2 | 0 | 3 | 1 | 0 | 1 | 0 | **7** |
关务报关员 | 1 | 2 | 1 | 2 | 1 | 1 | 1 | 0 | **9** |
工程文员 | 0 | 1 | 1 | 2 | 1 | 0 | 0 | 0 | **5** |
招聘专员 | 0 | 1 | 2 | 4 | 3 | 0 | 0 | 0 | **10** |
管理课长 | 2 | 2 | 1 | 6 | 0 | 0 | 0 | 0 | **11** |
**合计** | **8** | **17** | **13** | **28** | **24** | **1** | **3** | **1** | **95** |

## 三、维度视角:哪些维度是普遍的,哪些是偶发的

| dim | 出现于几份 JD | 条数 | 性质 |
|---|---|---|---|
**D 技能** | **10 / 10** | 28 | **唯一全员必有的维度** |
**B 教育** | **10 / 10** | 17 | 全员必有(学历);专业 6/10 |
**E 素质** | 9 / 10 | 24 | 几乎全员,但**全部不可机判** |
**C 经历** | 9 / 10 | 13 | 人资专员缺年限门槛 |
**A 人口** | **5 / 10** | 8 | 年龄 4 + 性别 3 + 1 显式"不限" |
**G 合规** | 3 / 10 | 3 | 跟单、人资、关务 |
**F 资质** | 1 / 10 | 1 | 只有关务的"合规培训考核" |
**H 语言** | 1 / 10 | 1 | 只有品质经理的英语 |

**95 条原子要求 → 库里现在只有 31 条。覆盖率 33%。**

## 四、可机判率

| dim | 条数 | 可判 | 需要什么才能判 |
|---|---|---|---|
D 技能 | 28 | ~26 | 已有 `hasSkill`;设备/域知识需词表 |
B 教育 | 17 | 12 | `education_rank`✅;**major ⬜**、**fullTime ⬜** |
C 经历 | 13 | 10 | `years_experience`✅;domain/industry ⬜ |
A 人口 | 8 | 8 | **gender ⬜**、`age`✅ |
G 合规 | 3 | 2 | 需 `hasClearance` ⬜ |
F 资质 | 1 | 1 | 需 `hasCertification` ⬜ |
H 语言 | 1 | 1 | 需 `languageLevel` ⬜ |
E 素质 | 24 | **0** | 结构上不可从简历判定 |
| **合计** | **95** | **~70(74%)** | |

**结论和单看副总助理时完全不同**:全体范围内 **74% 的要求是可机判的**,不是 33%。副总助理的 9 条素质是极端个例(它一份就占了 E 维度的 37.5%)。

## 五、标准补充项(不属于任何 dimension,别混进 requirement 表)

这些描述的是**岗位**,不是候选人 —— 应进 `:role_*` 个体:

岗位目的 · 职责权重/频次 · 工作地点 · 班制/工时 · 工作环境 · 是否出差 · 职业编码 · 职级 · 薪酬范围 · 发布日期/有效期 · 编制/招聘人数 · 招聘原因

其中 10 份 JD **全部缺失**的:工作地点、班制、发布日期、有效期、招聘原因。

---

## 六、这份清单的用途

1. **`requirement` 表从 31 条补到 95 条**(全部带 `dimension` + `code` + `verbatim` + `provenance='jd'`)
2. **候选侧只需补 5 个属性**:`gender` `major` `fullTime` `industryExperience` `languageLevel`(+`hasCertification`/`hasClearance` 共 7 个)
3. **E 维度 24 条统一标 `kind=soft, assessable=false`**,加分项是给它们一个 `evidence` 字段写明"用什么证明"
