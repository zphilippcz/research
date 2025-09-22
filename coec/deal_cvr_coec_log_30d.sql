-- =====================================================================
-- Deal CVR-COEC (30d, global) with shrink → category_path
-- Output: kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features
--
-- What this script does:
--   1) Build category_path from grt_l1..grt_l6.
--   2) Over the last 30 days, compute EWMA "effective" clicks & orders
--      for each DEAL and for each CATEGORY_PATH (HL = 5 days).
--   3) Compute category-level expected CVR with a weak global prior.
--   4) Compute deal-level CVR with a prior centered at the category CVR.
--   5) Form COEC = observed_deal_CVR / expected_category_CVR.
--   6) Convert to log-scale and clamp (robust to outliers).
--   7) Apply shrink toward the category baseline using clicks-based weight:
--        w = clicks_eff_deal / (clicks_eff_deal + τ_clicks), τ_clicks = 8
--      plus a low-data gate: if clicks_eff_deal < 3 → hard fallback.
--
-- Why log-COEC?
--   - Symmetric: 2x above vs 0.5x below are ± the same distance.
--   - More stable variance for tree models, safer to clamp to [-1.5, +1.5].
--
-- NOTE (PATCH #1 to step 7): Instead of shrinking/falling back to 0 (log(1)),
--       we shrink/fallback to category-vs-global log-COEC (lg_coec_cat).
--       This reduces zeros and distribution skew.
--
-- Key outputs:
--   - deal_id
--   - category_path
--   - deal_cvr_coec_log_30d  <-- final feature to feed into Vespa
--   - (diagnostics) clicks/orders evidence, expected CVR, weight, flags
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
    7.0  AS halflife,          -- EWMA half-life in days (recommend 4–6 for CVR; here 7 for stability)
    1e-6 AS eps,               -- numerical floor for divides & logs
    -1.2 AS L,                 -- log clamp low (tighter to reduce outliers)
     1.2 AS U,                 -- log clamp high
    10.0 AS k_prior,           -- pseudo-clicks strength for Beta prior (category & deal)
     8.0 AS tau_clicks,        -- shrink τ: deal weight w = n/(n+τ) at n=8 ⇒ w=0.5
     2.0 AS min_clk_eff        -- low-data gate: if clicks_eff_deal < 2 → fallback
),

-- --------------------------
-- Precompute α_EWMA from half-life
-- α = 1 - 0.5^(1/HL)
-- --------------------------
alpha_ctx AS (
  SELECT
    halflife,
    1 - POW(0.5, 1/halflife) AS alpha_ewma,
    eps, L, U, k_prior, tau_clicks, min_clk_eff
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
    SUM(sum_number_of_clicks)                                               AS clicks_day,
    SUM(sum_number_of_orders)                                               AS orders_day
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
-- EWMA evidence on DEAL level:
--   clicks_eff_deal, orders_eff_deal
--   (non-recursive EWMA via windowed partial sums)
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
    alpha_ewma * decay_pow * SUM(clicks_day * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS clicks_eff_deal,
    alpha_ewma * decay_pow * SUM(orders_day * decay_inv)
      OVER (PARTITION BY deal_id ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_deal
  FROM deal_idx
),
deal_now AS (
  -- one row per deal_id (state as of "today")
  SELECT * FROM deal_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY day_date DESC) = 1
),

-- --------------------------
-- EWMA evidence on CATEGORY_PATH level:
--   clicks_eff_cat, orders_eff_cat
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
    SUM(sum_number_of_clicks)                                               AS clicks_day_cat,
    SUM(sum_number_of_orders)                                               AS orders_day_cat
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
    alpha_ewma * decay_pow * SUM(clicks_day_cat * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS clicks_eff_cat,
    alpha_ewma * decay_pow * SUM(orders_day_cat * decay_inv)
      OVER (PARTITION BY category_path ORDER BY day_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_cat
  FROM cat_idx
),
cat_now AS (
  -- one row per category_path (state as of "today")
  SELECT * FROM cat_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY category_path ORDER BY day_date DESC) = 1
),

-- --------------------------
-- Global expected CVR (from all category paths) used as a fallback prior
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
--   cvr_deal = (orders_eff_deal + m_cat*k) / (clicks_eff_deal + k)
--   m_cat = COALESCE(category cvr_cat, m_global)
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
-- COEC (O/E) = cvr_deal / m_cat, then log + clamp
-- PATCH #2: also compute lg_coec_cat = log( category_CVR / global_CVR )
--           This is the category-vs-global baseline used for fallback & blending.
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
    GREATEST(a.L,
      LEAST(a.U,
        LOG(GREATEST(
          SAFE_DIVIDE(dc.cvr_deal, GREATEST(dc.m_cat, a.eps)),
          a.eps
        ))
      )
    ) AS lg_coec_deal,
    -- PATCH: log COEC (category vs global) baseline
    GREATEST(a.L,
      LEAST(a.U,
        LOG(GREATEST(
          SAFE_DIVIDE(dc.m_cat, GREATEST(gp.m_global, a.eps)),
          a.eps
        ))
      )
    ) AS lg_coec_cat
  FROM deal_cvr dc
  CROSS JOIN global_prior gp
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- Shrink toward category baseline (lg_coec_cat) with clicks-based weight:
--   w = clicks_eff_deal / (clicks_eff_deal + τ)
-- Low-data gate: if clicks_eff_deal < min_clk_eff → return lg_coec_cat (category-vs-global)
-- PATCH #3: use lg_coec_cat both in gate and as the back-off in blending
-- --------------------------
blended_pre AS (
  SELECT
    dco.*,
    a.tau_clicks,
    a.min_clk_eff,
    SAFE_DIVIDE(dco.clicks_eff_deal, dco.clicks_eff_deal + a.tau_clicks) AS w_deal
  FROM deal_coec dco
  CROSS JOIN alpha_ctx a
),
blended AS (
  SELECT
    bpre.*,
    CASE
      WHEN bpre.clicks_eff_deal < bpre.min_clk_eff
        THEN bpre.lg_coec_cat                                            -- gate fallback: category vs global
      ELSE bpre.w_deal * bpre.lg_coec_deal + (1 - bpre.w_deal) * bpre.lg_coec_cat
    END AS deal_cvr_coec_log_30d
  FROM blended_pre AS bpre
)

-- =========================
-- Final projection (one row per deal_id)
-- =========================
SELECT
  b.deal_id,
  b.category_path,

  -- FINAL FEATURE: log-COEC after shrink and gate (now centered at category-vs-global, not 0)
  b.deal_cvr_coec_log_30d,

  -- Deal-level (non-log) and CVR:
  b.cvr_deal                         AS deal_cvr,
  b.coec_deal                        AS deal_coec,        -- non-log COEC (deal vs category)

  -- Category-level CVR and non-log COEC (category vs global):
  b.m_cat                            AS category_cvr,
  SAFE_DIVIDE(
    b.m_cat,
    GREATEST(gp.m_global, a.eps)
  )                                  AS category_coec,

  -- (Diagnostics)
  b.clicks_eff_deal,
  b.orders_eff_deal,
  b.lg_coec_deal,
  b.lg_coec_cat,                                         -- useful to inspect baseline
  b.w_deal,
  (b.clicks_eff_deal < a.min_clk_eff) AS is_low_data_gate,
  b.used_global_prior
FROM blended AS b
CROSS JOIN global_prior AS gp
CROSS JOIN alpha_ctx AS a;
