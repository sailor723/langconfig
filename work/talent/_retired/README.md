# 已退役的字段模板

这两个文件的内容**已经全部并入 `work/talent/field_schema.yaml`**。
保留它们的原因只有一个:`backend/scripts/talent/build_field_schema.py` 还从这儿读
实测的 presence 数据,以便重新生成合并结果。

## 为什么退役

原来有 `jd_schema.yaml`(42 字段)+ `cv_schema.yaml`(31 字段)+ 一张手写 crosswalk,
是三份账。三份账一定有一份会漏改 —— 实测就是这样:合并后手写的那 9 条
「不可比」判定没跟着更新,可比数虚高了 9 个。

现在:
    field_schema.yaml   字段全集(唯一)
    ├─ jd: {...}        JD 模板裁剪依据
    └─ cv: {...}        CV 模板裁剪依据
    compare             **算出来的**,不是手写的

## 不要在这里新增字段

新字段加在 `field_schema.yaml`。这两个文件只在"要重新生成合并结果"时才需要改。

