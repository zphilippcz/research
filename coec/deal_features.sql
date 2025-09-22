-- =====================================================================
-- Deal CVR-COEC + gPPI-COEC (30d, global) with shrink → category_path
-- Output: kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features
--
-- What this script does:
--   1) Build category_path from grt_l1..grt_l6.
--   2) Over the last 30 days, compute EWMA "effective" metrics
--      for each DEAL and for each CATEGORY_PATH (HL = 7 days):
--        - clicks, orders  (for CVR)
--        - impressions, m1 (gross profit) (for gPPI)
--   3) Compute category-level expectations with a weak global prior.
--   4) Compute deal-level smoothed metrics with priors centered at category.
--   5) Form COEC = Observed / Expected (for CVR and for gPPI).
--   6) Convert to log-scale and clamp (robust to outliers).
--   7) Apply shrink toward a baseline using evidence-based weights:
--        - CVR:   w_clicks = clicks_eff_deal / (clicks_eff_deal + τ_clicks)
--        - gPPI:  w_impr   = impr_eff_deal   / (impr_eff_deal   + τ_impr)
--      Baselines:
--        - CVR baseline:   category-vs-global log-COEC (lg_coec_cat)
--        - gPPI baseline:  category-vs-global log-COEC (lg_coec_gppi_cat)
--
-- Key outputs:
--   - deal_cvr_coec_log_30d      <-- CVR feature for Vespa/ML
--   - deal_gppi_coec_log_30d     <-- gPPI feature for Vespa/ML
--   - diagnostics (coverage, weights, raw metrics)
-- =====================================================================

CREATE OR REPLACE TABLE
  `kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features`
AS
-- --------------------------
-- Tunable parameters
-- --------------------------
WITH
params AS (
  SELECT
    7.0  AS halflife,          -- EWMA half-life in days (stability)
    1e-6 AS eps,               -- numerical floor for divides & logs
    -1.2 AS L,                 -- log clamp low (tighter to reduce outliers)
     1.2 AS U,                 -- log clamp high
    -- CVR priors/shrink
    10.0 AS k_prior,           -- pseudo-clicks for CVR priors (category & deal)
     8.0 AS tau_clicks,        -- shrink τ for CVR (50% weight at ~8 eff. clicks)
     2.0 AS min_clk_eff,       -- CVR gate: if clicks_eff_deal < 2 → fallback to baseline
    -- gPPI priors/shrink
    300.0 AS k_impr_cat,       -- pseudo-impressions for category gPPI prior
    300.0 AS k_impr_deal,      -- pseudo-impressions for deal gPPI prior
    200.0 AS tau_impr,         -- shrink τ for gPPI (50% weight at ~200 eff. impressions)
     50.0 AS min_impr_eff      -- gPPI gate: if impr_eff_deal < 50 → fallback to baseline
),

-- --------------------------
-- Precompute α_EWMA from half-life
-- α = 1 - 0.5^(1/HL)
-- --------------------------
alpha_ctx AS (
  SELECT
    halflife,
    1 - POW(0.5, 1/halflife) AS alpha_ewma,
    eps, L, U,
    k_prior, tau_clicks, min_clk_eff,
    k_impr_cat, k_impr_deal, tau_impr, min_impr_eff
  FROM params
),

-- --------------------------
-- Build daily source with category_path
-- The source table is already daily; we still use SUM() for safety (dedupe).
-- --------------------------
src AS (
  SELECT
    SAFE.PARSE_DATE('%Y-%m-%d', day)                                       AS day_date,
    shown_deal                                                              AS deal_id,
    ARRAY_TO_STRING(
      ARRAY(
        SELECT level
        FROM UNNEST([grt_l1, grt_l2, grt_l3, grt_l4, grt_l5, grt_l6]) AS level
        WHERE level IS NOT NULL AND TRIM(level) <> ''
      ),
      ' > '
    )                                                                       AS category_path,
    -- CVR ingredients (daily)
    SUM(sum_number_of_clicks)                                               AS clicks_day,
    SUM(sum_number_of_orders)                                               AS orders_day,
    -- gPPI ingredients (daily)
    SUM(sum_number_of_impressions)                                          AS impr_day,
    SUM(sum_m1_vfm)                                                         AS m1_day
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.daily-search-relevance-dataset`
  WHERE shown_deal IS NOT NULL
  GROUP BY 1,2,3
),

-- --------------------------
-- Restrict to rolling 30 days
-- --------------------------
win30 AS (
  SELECT * FROM src
  WHERE day_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- --------------------------
-- EWMA evidence on DEAL level (clicks, orders, impressions, m1)
--   non-recursive EWMA via windowed partial sums
-- --------------------------
deal_idx AS (
  SELECT
    w.*,
    a.alpha_ewma,
    ROW_NUMBER() OVER (PARTITION BY w.deal_id ORDER BY w.day_date)                                  AS rn,
    POW(1 - a.alpha_ewma, -ROW_NUMBER() OVER (PARTITION BY w.deal_id ORDER BY w.day_date))          AS decay_inv,
    POW(1 - a.alpha_ewma,  ROW_NUMBER() OVER (PARTITION BY w.deal_id ORDER BY w.day_date))          AS decay_pow
  FROM win30 w
  CROSS JOIN alpha_ctx a
),
deal_ewma AS (
  SELECT
    deal_id,
    category_path,
    day_date,
    -- CVR effective evidence
    alpha_ewma * decay_pow * SUM(clicks_day * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS clicks_eff_deal,
    alpha_ewma * decay_pow * SUM(orders_day * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_deal,
    -- gPPI effective evidence
    alpha_ewma * decay_pow * SUM(impr_day  * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS impr_eff_deal,
    alpha_ewma * decay_pow * SUM(m1_day    * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS m1_eff_deal
  FROM deal_idx
),
deal_now AS (
  -- one row per deal_id (state as of "today")
  SELECT * FROM deal_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY day_date DESC) = 1
),

-- --------------------------
-- EWMA evidence on CATEGORY_PATH level (clicks, orders, impressions, m1)
-- --------------------------
cat_src AS (
  SELECT
    SAFE.PARSE_DATE('%Y-%m-%d', day)                                       AS day_date,
    ARRAY_TO_STRING(
      ARRAY(
        SELECT level
        FROM UNNEST([grt_l1, grt_l2, grt_l3, grt_l4, grt_l5, grt_l6]) AS level
        WHERE level IS NOT NULL AND TRIM(level) <> ''
      ),
      ' > '
    )                                                                       AS category_path,
    -- CVR
    SUM(sum_number_of_clicks)                                               AS clicks_day_cat,
    SUM(sum_number_of_orders)                                               AS orders_day_cat,
    -- gPPI
    SUM(sum_number_of_impressions)                                          AS impr_day_cat,
    SUM(sum_m1_vfm)                                                         AS m1_day_cat
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.daily-search-relevance-dataset`
  WHERE (grt_l1 IS NOT NULL OR grt_l2 IS NOT NULL OR grt_l3 IS NOT NULL
         OR grt_l4 IS NOT NULL OR grt_l5 IS NOT NULL OR grt_l6 IS NOT NULL)
  GROUP BY 1,2
),
cat_win30 AS (
  SELECT * FROM cat_src
  WHERE day_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),
cat_idx AS (
  SELECT
    c.*,
    a.alpha_ewma,
    ROW_NUMBER() OVER (PARTITION BY c.category_path ORDER BY c.day_date)                             AS rn,
    POW(1 - a.alpha_ewma, -ROW_NUMBER() OVER (PARTITION BY c.category_path ORDER BY c.day_date))     AS decay_inv,
    POW(1 - a.alpha_ewma,  ROW_NUMBER() OVER (PARTITION BY c.category_path ORDER BY c.day_date))     AS decay_pow
  FROM cat_win30 c
  CROSS JOIN alpha_ctx a
),
cat_ewma AS (
  SELECT
    category_path,
    day_date,
    -- CVR effective evidence
    alpha_ewma * decay_pow * SUM(clicks_day_cat * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS clicks_eff_cat,
    alpha_ewma * decay_pow * SUM(orders_day_cat * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_cat,
    -- gPPI effective evidence
    alpha_ewma * decay_pow * SUM(impr_day_cat * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS impr_eff_cat,
    alpha_ewma * decay_pow * SUM(m1_day_cat   * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS m1_eff_cat
  FROM cat_idx
),
cat_now AS (
  -- one row per category_path (state as of "today")
  SELECT * FROM cat_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY category_path ORDER BY day_date DESC) = 1
),

-- --------------------------
-- Global expected CVR (from categories) used as fallback prior
-- --------------------------
global_prior AS (
  SELECT SAFE_DIVIDE(SUM(orders_eff_cat), NULLIF(SUM(clicks_eff_cat), 0)) AS m_global
  FROM cat_now
),

-- --------------------------
-- Category expected CVR with weak global prior (k = 10)
--   cvr_cat = (orders_eff_cat + m_global*k) / (clicks_eff_cat + k)
-- --------------------------
cat_cvr AS (
  SELECT
    c.category_path,
    c.clicks_eff_cat,
    c.orders_eff_cat,
    gp.m_global,
    SAFE_DIVIDE(c.orders_eff_cat + gp.m_global * a.k_prior,
                c.clicks_eff_cat + a.k_prior)                              AS cvr_cat
  FROM cat_now c
  CROSS JOIN global_prior gp
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- Deal CVR with prior centered at category CVR (fallback to global m if category missing)
-- --------------------------
deal_cvr AS (
  SELECT
    d.deal_id,
    d.category_path,
    d.clicks_eff_deal,
    d.orders_eff_deal,
    COALESCE(c.cvr_cat, gp.m_global) AS m_cat,
    (c.cvr_cat IS NULL)              AS used_global_prior,
    SAFE_DIVIDE(
      d.orders_eff_deal + COALESCE(c.cvr_cat, gp.m_global) * a.k_prior,
      d.clicks_eff_deal + a.k_prior
    ) AS cvr_deal
  FROM deal_now d
  LEFT JOIN cat_cvr c USING (category_path)
  CROSS JOIN global_prior gp
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- COEC (O/E) for CVR, then log + clamp; also compute lg_coec_cat baseline
-- --------------------------
deal_coec AS (
  SELECT
    dc.deal_id,
    dc.category_path,
    dc.clicks_eff_deal,
    dc.orders_eff_deal,
    dc.m_cat,
    dc.used_global_prior,
    dc.cvr_deal,
    SAFE_DIVIDE(dc.cvr_deal, GREATEST(dc.m_cat, a.eps)) AS coec_deal,
    -- log COEC (deal vs category)
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(dc.cvr_deal, GREATEST(dc.m_cat, a.eps)), a.eps))
    )) AS lg_coec_deal,
    -- category-vs-global baseline (log)
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(dc.m_cat, GREATEST(gp.m_global, a.eps)), a.eps))
    )) AS lg_coec_cat
  FROM deal_cvr dc
  CROSS JOIN global_prior gp
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- Shrink CVR toward category baseline (lg_coec_cat) with clicks-based weight
-- --------------------------
blended_cvr AS (
  SELECT
    dco.*,
    a.tau_clicks,
    a.min_clk_eff,
    SAFE_DIVIDE(dco.clicks_eff_deal, dco.clicks_eff_deal + a.tau_clicks) AS w_deal,
    CASE
      WHEN dco.clicks_eff_deal < a.min_clk_eff
        THEN dco.lg_coec_cat
      ELSE (SAFE_DIVIDE(dco.clicks_eff_deal, dco.clicks_eff_deal + a.tau_clicks) * dco.lg_coec_deal
            + (1 - SAFE_DIVIDE(dco.clicks_eff_deal, dco.clicks_eff_deal + a.tau_clicks)) * dco.lg_coec_cat)
    END AS deal_cvr_coec_log_30d
  FROM deal_coec dco
  CROSS JOIN alpha_ctx a
),

-- ====================================================================
-- gPPI pipeline (gross profit per impression) — parallel to CVR
-- ====================================================================

-- Global expected gPPI from categories
gppi_global_prior AS (
  SELECT SAFE_DIVIDE(SUM(m1_eff_cat), NULLIF(SUM(impr_eff_cat), 0)) AS m_global_gppi
  FROM cat_now
),

-- Category expected gPPI with weak global prior
cat_gppi AS (
  SELECT
    c.category_path,
    c.impr_eff_cat,
    c.m1_eff_cat,
    gp.m_global_gppi,
    SAFE_DIVIDE(c.m1_eff_cat + gp.m_global_gppi * a.k_impr_cat,
                c.impr_eff_cat + a.k_impr_cat)                           AS gppi_cat
  FROM cat_now c
  CROSS JOIN gppi_global_prior gp
  CROSS JOIN alpha_ctx a
),

-- Deal gPPI with prior centered at category gPPI
deal_gppi AS (
  SELECT
    d.deal_id,
    d.category_path,
    d.impr_eff_deal,
    d.m1_eff_deal,
    COALESCE(c.gppi_cat, gp.m_global_gppi) AS gppi_cat_filled,
    SAFE_DIVIDE(
      d.m1_eff_deal + COALESCE(c.gppi_cat, gp.m_global_gppi) * a.k_impr_deal,
      d.impr_eff_deal + a.k_impr_deal
    ) AS gppi_deal
  FROM deal_now d
  LEFT JOIN cat_gppi c USING (category_path)
  CROSS JOIN gppi_global_prior gp
  CROSS JOIN alpha_ctx a
),

-- COEC for gPPI, log + clamp; also category-vs-global baseline (log)
deal_gppi_coec AS (
  SELECT
    g.*,
    SAFE_DIVIDE(g.gppi_deal, GREATEST(g.gppi_cat_filled, a.eps)) AS gppi_coec,
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(g.gppi_deal, GREATEST(g.gppi_cat_filled, a.eps)), a.eps))
    )) AS lg_coec_gppi_deal,
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(g.gppi_cat_filled, GREATEST(gp.m_global_gppi, a.eps)), a.eps))
    )) AS lg_coec_gppi_cat
  FROM deal_gppi g
  CROSS JOIN gppi_global_prior gp
  CROSS JOIN alpha_ctx a
),

-- Shrink gPPI toward category baseline with impressions-based weight
blended_gppi AS (
  SELECT
    gg.*,
    a.tau_impr,
    a.min_impr_eff,
    SAFE_DIVIDE(gg.impr_eff_deal, gg.impr_eff_deal + a.tau_impr) AS w_impr,
    CASE
      WHEN gg.impr_eff_deal < a.min_impr_eff
        THEN gg.lg_coec_gppi_cat
      ELSE (SAFE_DIVIDE(gg.impr_eff_deal, gg.impr_eff_deal + a.tau_impr) * gg.lg_coec_gppi_deal
            + (1 - SAFE_DIVIDE(gg.impr_eff_deal, gg.impr_eff_deal + a.tau_impr)) * gg.lg_coec_gppi_cat)
    END AS deal_gppi_coec_log_30d
  FROM deal_gppi_coec gg
  CROSS JOIN alpha_ctx a
)

-- =========================
-- Final projection (one row per deal_id)
-- =========================
SELECT
  -- keys
  cvr.deal_id,
  cvr.category_path,

  -- FINAL FEATURES for ranking
  cvr.deal_cvr_coec_log_30d,
  gppi.deal_gppi_coec_log_30d,

  -- CVR diagnostics
  cvr.cvr_deal                         AS deal_cvr,
  cvr.coec_deal                        AS deal_coec,             -- non-log (deal vs category)
  cvr.lg_coec_deal,
  cvr.lg_coec_cat,                                             -- category-vs-global baseline (log)
  cvr.clicks_eff_deal,
  cvr.orders_eff_deal,
  cvr.w_deal,
  (cvr.clicks_eff_deal < (SELECT min_clk_eff FROM alpha_ctx)) AS is_low_data_gate_cvr,
  cvr.used_global_prior,

  -- gPPI diagnostics
  gppi.gppi_deal,
  gppi.gppi_cat_filled                AS gppi_cat,
  gppi.gppi_coec,
  gppi.lg_coec_gppi_deal,
  gppi.lg_coec_gppi_cat,                                      -- category-vs-global baseline (log)
  gppi.impr_eff_deal,
  gppi.m1_eff_deal,
  gppi.w_impr,
  (gppi.impr_eff_deal < (SELECT min_impr_eff FROM alpha_ctx)) AS is_low_data_gate_gppi

FROM blended_cvr AS cvr
LEFT JOIN blended_gppi AS gppi
  USING (deal_id, category_path);
