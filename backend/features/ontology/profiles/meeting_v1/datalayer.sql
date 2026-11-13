-- meeting_v1 数据层（部署用）：库里必须长成这个样子，本体才有东西可编译。
--
-- 为什么这份文件在 profile 里：01-structure.ttl 把 :physicalTable 指向 meeting_hub_raw 和两个
-- 视图，可是"这些关系从哪来"过去只写在 agent 的交付报告里 —— 换一台机器部署（ECS）就只剩
-- 「relation meeting_hub_raw does not exist」，四族门禁全红，而声明本身没错。声明和它的
-- 数据层必须一起进仓库。
--
-- ① 表 meeting_hub_raw —— 客户原始导出的逐行装载：3562 行、14 列、全 text。
--    客户导出的第一行是一句标题，第二行才是表头，而表头里的 "时长\n(分钟)" 又跨了一行，
--    所以表头不进库，列名按出现顺序固定为 c0..c13，类型化留给视图/指标里的 ::date ::int。
--    装载（在目标库 meeting_hub 上执行，路径按部署机修改）：
--      \copy meeting_hub_raw from program 'tail -n +4 "client/team-1/会议汇总-原始导出.csv"' with (format csv)
--    核对（三个数必须对上，否则后面的口径全是错的）：
--      select count(*) from meeting_hub_raw;                        -- 3562
--      select count(*) from meeting_hub_raw where c3 = '工作汇报';   -- 与 S0 量库报告一致
--
-- ② 两个视图 —— 本本体授权的数据层（Q8 确认）：只做机械类型化与会议键，不含业务归一化；
--    改口径请在声明里改，不要在这里加 CASE。

CREATE TABLE IF NOT EXISTS meeting_hub_raw (
  c0  text,  -- 厂区
  c1  text,  -- 日期
  c2  text,  -- 序号
  c3  text,  -- 会议类型
  c4  text,  -- 会议名称
  c5  text,  -- 时段
  c6  text,  -- 时长（分钟）
  c7  text,  -- 主导人
  c8  text,  -- 参会人员（顿号/逗号/斜杠分隔）
  c9  text,  -- 场所
  c10 text,  -- 会议纪要
  c11 text,  -- 责任人
  c12 text,  -- 完成时间
  c13 text   -- 实际完成时间
);

-- 出席记录：一行 = 一场会 × 一个人，attendance_key 唯一。
-- 会议键 = (厂区, 会议日期, 会议名称, 时段, 主导人)（Q3 确认的四元组，主导人为空用 '' 占位）。
CREATE OR REPLACE VIEW meeting_hub_attendance AS
WITH exp AS (
  SELECT c0||'|'||c1||'|'||c4||'|'||c5||'|'||coalesce(c7,'') AS meeting_key,
         btrim(unnest(regexp_split_to_array(c8, '[,、;；/／[:space:]]'))) AS person,
         max(c6::int) OVER (PARTITION BY c0, c1, c4, c5, coalesce(c7,'')) AS duration_minutes,
         min(c3)      OVER (PARTITION BY c0, c1, c4, c5, coalesce(c7,'')) AS meeting_type,
         c0 AS site_code, c1::date AS meeting_date
    FROM meeting_hub_raw)
SELECT DISTINCT meeting_key||'|'||person AS attendance_key,
       meeting_key, site_code, meeting_date, duration_minutes, meeting_type, person
  FROM exp
 WHERE person <> '';

-- 会议：一行 = 一场会，在出席记录上 SELECT DISTINCT。
CREATE OR REPLACE VIEW meeting_hub_meeting AS
SELECT DISTINCT meeting_key, site_code, meeting_date, duration_minutes, meeting_type
  FROM meeting_hub_attendance;
