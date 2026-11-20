# 要求分类方案(requirement taxonomy)· 副总助理 15 条

> 目的:给每条要求一个**稳定的分类码**,让它可以入库、被门禁检查、被界面分组。
>
> 为什么要两个轴:现在的 `kind` 只回答"怎么算分",不回答"考的是候选人的哪一面"。
> 两者混在一起,就会把「女性」和「Office」都当成"要求"而无法区分处置方式。

---

## 一、两个正交轴

| 轴 | 回答什么 | 取值 | 谁用 |
|---|---|---|---|
**dimension**(维度) | 这条要求考察候选人的**哪个方面** | 7 类,见下 | 界面分组、标准映射、缺属性检测 |
**kind**(形式) | 这条要求**怎么算分** | binary / years / product / equipment / capability / composite / soft / credential | 评分器 `fit_component` |

同一个 dimension 下可以有不同的 kind。例:
- dimension=`skill` + kind=`composite` → Office(Word/Excel/PPT/AI)
- dimension=`skill` + kind=`product` → 单一软件
- dimension=`competency` + kind=`soft` → 沟通能力

---

## 二、七个维度(封闭集合,不再增加)

| 码 | 维度 | 定义 | 候选侧属性 | 值来自哪个标准 |
|---|---|---|---|---|
**A** | `demographic` 人口属性 | 与生俱来或难以改变的属性 | `gender`(待建)、`age`(已有) | 无标准(客户声明) |
**B** | `education` 教育 | 学历与专业 | `education_rank`(已有)、`major`(待建) | 人社部学历序列 / ESCO `qualification` |
**C** | `experience` 经历 | 工作年限、职能域、行业、在岗时长 | `years_experience`(已有)、`employmentHistory[]`(待建)、`industryExperience`(待建) | O\*NET `Job Zone` / `Work Experience` |
**D** | `skill` 技能 | 可操作的工具、设备、能力 | `hasSkill`(已有) | ESCO essential/optional / O\*NET `Tools & Technology` |
**E** | `competency` 素质能力 | 行为倾向与认知能力 | 无(简历不可判) | HR Open Standards `Competency` / O\*NET `Abilities` |
**F** | `credential` 资质证书 | 执照、认证、培训记录 | `hasCertification`(待建) | 人社部《国家职业技能标准》等级 / O\*NET `Credentials` |
**G** | `compliance` 合规约束 | 法律与公司制度要求 | `hasClearance`(待建) | ISO/TC 260 / 公司章程 |

**为什么封闭**:多一个维度就要多一套候选侧属性和一套门禁。7 类已覆盖 10 份 JD 里出现的全部要求形态;新的要求往这 7 类里归,不新开类。

---

## 三、副总助理 15 条,逐条归类

| 码 | dimension | kind | tier | 原文 | 候选侧属性 | 状态 |
|---|---|---|---|---|---|---|
`VP-A1` | **A** demographic | binary | essential | 女性 | `gender` ⬜ | 待建属性 |
`VP-A2` | **A** demographic | range | essential | 25-38岁 | `age` ✅ | 可直接建 |
`VP-B1` | **B** education | ordinal | essential | 全日制大专及以上 | `education_rank` ✅ | ABox 有;评分已退出闸门 |
`VP-B2` | **B** education | binary | **desirable** | 中文、文秘类专业优先 | `major` ⬜ | 待建属性 |
`VP-C1` | **C** experience | composite | essential | 2年以上文职类、助理类、管理类工厂**工作经验** | `years_experience` ✅ + 职能域 ⬜ + 行业 ⬜ | kind 现错为 capability |
`VP-D1` | **D** skill | composite | essential | Office办公软件（Word/ Excel/ PPT/ AI） | `hasSkill` ✅ | 缺 AI 部件 |
`VP-E1` | **E** competency | soft | essential | 原则性强 | — | 不可评 |
`VP-E2` | **E** competency | soft | essential | 责任心突出 | — | 不可评 |
`VP-E3` | **E** competency | soft | essential | 敢于担当 | — | 不可评 |
`VP-E4` | **E** competency | soft | essential | 坚持日清日结 | — | 不可评 |
`VP-E5` | **E** competency | soft | essential | 具备良好的奋斗精神 | — | 不可评 |
`VP-E6` | **E** competency | soft | essential | 沟通能力好 | — | 不可评 |
`VP-E7` | **E** competency | soft | essential | 执行能力强 | — | 不可评 |
`VP-E8` | **E** competency | soft | essential | 逻辑清晰 | — | 不可评 |
`VP-E9` | **E** competency | soft | essential | 数据敏感 | — | 不可评 |

**分布:A=2 · B=2 · C=1 · D=1 · E=9 · F=0 · G=0 → 15 条**

---

## 四、维度内部再分小类(便于界面折叠)

| dimension | 小类 | 副总助理命中 |
|---|---|---|
A `demographic` | `gender` / `age` / `marital` / `hukou` | gender×1, age×1 |
B `education` | `level` / `major` / `schoolTier` / `fullTime` | level×1, major×1, **fullTime×1(隐含在"全日制"里)** |
C `experience` | `years` / `domain` / `industry` / `tenure` | years+domain+industry 三条合为一条复合要求 |
D `skill` | `product` / `equipment` / `capability` / `domain` | Office = product×3(Word/Excel/PPT)+ product×1(AI 工具) |
E `competency` | `behavioral`(行为)/ `cognitive`(认知)/ `motivational`(动机) | behavioral×7(E1–E7),cognitive×2(E8 逻辑、E9 数据) |
F `credential` | `license` / `certificate` / `training` | 无 |
G `compliance` | `legal` / `corporate` | 无 |

**注意 B 里藏着一条被忽略的要求**:「**全日制**大专及以上」的 `fullTime` 是**独立的一个判定**(成人教育/自考 vs 全日制),而现在模型里完全没有。

---

## 五、这个分类带来的三个直接好处

**1. 缺属性可以自动检测**
每个 dimension 声明它依赖哪些候选侧属性。要建一条要求时,如果属性缺失 → 门禁直接报"无法评估",而不是静默变成 `assessable=false`。

```
dimension A 依赖 [gender, age]
dimension B 依赖 [education_rank, major, fullTime]
...
```

**2. 不可评的 9 条会聚成一类,而不是散落 9 行**
E 维度 9 条全部 `kind=soft` → 界面可以折成一行「素质能力 9 项(不可评估)」,而不是让 9 行噪音把 5 条可判要求淹掉。

**3. 标准补充有明确的落点**
L2(标准补充)往哪个 dimension 填,一目了然:

| 标准补充项 | 落到哪 |
|---|---|
岗位目的 | 不属于任何 dimension —— 它是 **岗位属性**,不是候选人要求 |
职责权重/频次 | 同上 |
工作地点/班制/环境/出差 | 同上 |
资质证书 | **F** credential |
职业编码/职级 | 岗位属性(不影响候选人判定) |

**这条界线很重要**:标准里很多字段描述的是**岗位**,不是**候选人**。它们不该进 `requirement` 表,而应进岗位侧(`:role_*` 个体)。

---

## 六、建议的表结构增量

```sql
ALTER TABLE requirement ADD COLUMN dimension text NOT NULL DEFAULT 'skill';
ALTER TABLE requirement ADD COLUMN subdimension text;      -- gender / level / years / behavioral …
ALTER TABLE requirement ADD COLUMN code text UNIQUE;       -- VP-A1 / VP-D1 / …
ALTER TABLE requirement ADD COLUMN provenance text NOT NULL DEFAULT 'jd';  -- jd | standard
```

三类要求的最终计数(副总助理):

| dimension | 条数 | 可机判 |
|---|---|---|
A 人口属性 | 2 | 2(需补 gender) |
B 教育 | 2(+1 隐含 fullTime) | 2–3(需补 major/fullTime) |
C 经历 | 1 | 1(需拆 domain/industry) |
D 技能 | 1 | 1(需补 AI 部件) |
E 素质能力 | 9 | **0** |
F 资质证书 | 0 | — |
G 合规 | 0 | — |
**合计** | **15** | **5–6 / 15** |
