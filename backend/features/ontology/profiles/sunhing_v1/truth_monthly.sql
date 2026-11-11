-- 第二条手写 SQL 路线：直接读源表算 22 个 KPI 的月度序列 + 3 条 ROE 趋势，
-- 与 fact_kpi_monthly / fact_roe_summary 的落地值逐期对照。
-- 不经过本体、不经过 metrics_ext.ttl：这一条是独立核对线。
WITH h AS (SELECT * FROM dim_hr_monthly),
     f AS (SELECT * FROM dim_finance_monthly),
     p AS (SELECT * FROM dim_production_monthly),
     d AS (SELECT * FROM dim_digital_monthly),
     l AS (SELECT * FROM dim_legal_monthly),
     s AS (SELECT * FROM dim_sentiment_monthly),
     m AS (SELECT * FROM dim_pmo_monthly),
     r AS (SELECT * FROM fact_roe_summary)
SELECT f.period,
       round(h.severance_completed_cumulative * 100.0 / NULLIF(h.severance_planned,0), 2)              AS k01,
       round(f.liability_resolved_cumulative_wan * 100.0
             / NULLIF(f.liability_resolved_cumulative_wan + f.liability_remaining_wan, 0), 2)           AS k02,
       round(h.severance_paid_cumulative_wan * 100.0 / NULLIF(h.severance_planned * 4.5, 0), 2)         AS k03,
       (l.new_labor_arbitration_cases + l.pending_labor_cases)                                           AS k04,
       round(p.critical_processes_running * 100.0 / NULLIF(p.total_processes,0), 2)                      AS k05,
       round(h.production_headcount * 100.0 / NULLIF(h.total_headcount,0), 2)                            AS k06,
       round(f.core_factory_net_profit_wan * 100.0 / NULLIF(f.total_mfg_net_profit_wan,0), 2)            AS k07,
       round(f.eco_partner_net_profit_wan * 100.0 / NULLIF(f.total_mfg_net_profit_wan,0), 2)             AS k08,
       round(d.reuse_rate_pct * d.digital_maturity_score / 100.0, 2)                                     AS k09,
       p.oee_pct                                                                                         AS k10,
       round(d.reuse_rate_pct, 2)                                                                        AS k12,
       round(f.reinvested_wan * 100.0 / NULLIF(f.cash_released_wan,0), 2)                                AS k13,
       round(h.employee_partner_converted * 100.0 / NULLIF(h.total_headcount,0), 2)                      AS k15,
       round(1.0 + (f.liability_total_wan / NULLIF(f.net_profit_wan * 10, 0)), 2)                        AS k16,
       (SELECT round(sum(x.completed_on_time) * 100.0 / NULLIF(count(*),0), 2)
          FROM raw_pmo x WHERE x.month = f.period AND x.status = 'completed')                            AS k19,
       (l.major_group_incidents + l.near_miss_group_incidents)                                           AS k20,
       round(s.change_readiness_score * s.employee_satisfaction / 10.0, 2)                               AS k21,
       round(h.severance_dispute_count * 100.0 / NULLIF(h.severance_completed_cumulative,0), 2)          AS rs01,
       s.severance_satisfaction                                                                          AS rs02,
       (l.major_group_incidents * 10 + l.near_miss_group_incidents * 3)                                   AS rs03,
       l.customs_compliance_pct                                                                          AS rs04,
       l.customs_penalties_wan                                                                           AS rs05,
       r.roe                                                                                             AS roe,
       r.net_profit_margin                                                                               AS npm,
       r.asset_turnover                                                                                  AS atn,
       r.equity_multiplier                                                                               AS em,
       round(r.net_profit_margin * r.asset_turnover * r.equity_multiplier / 100.0, 2)                     AS roe_identity_check
FROM f
JOIN h ON h.period = f.period
JOIN p ON p.period = f.period
JOIN d ON d.period = f.period
JOIN l ON l.period = f.period
JOIN s ON s.period = f.period
JOIN m ON m.period = f.period
JOIN r ON r.period = f.period
ORDER BY f.period;
