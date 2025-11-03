-- =====================================================================
-- OPTION-LEVEL CVR-COEC + GPPI-COEC (30d, global) with shrink → DEAL uplift
-- Output: kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_option_features
--
-- Concept:
--   • Options do not have their own clicks or impressions logs.
--     We model each option as a "split" of the parent deal.
--
--   CVR (per-click):
--       Observed:   p_hat_opt  = orders_eff_opt / clicks_eff_deal(parent)
--       Expected:   m_opt_cvr  = deal_cvr(parent) * s_opt_orders
--       Smoothed:   cvr_opt    = (orders_eff_opt + m_opt_cvr * k_clicks)
--                                / (clicks_eff_deal + k_clicks)
--
--   GPPI (per-impression):
--       Observed:   gppi_hat_opt = m1_eff_opt / impr_eff_deal(parent)
--       Expected:   m_opt_gppi   = gppi_deal(parent) * s_opt_value
--       Smoothed:   gppi_opt     = (m1_eff_opt + m_opt_gppi * k_impr_opt)
--                                / (impr_eff_deal + k_impr_opt)
--
--   Both metrics are log-transformed, clamped, and shrunk toward the
--   parent deal uplift. If option evidence is too low → fallback to parent.
--
-- =====================================================================

CREATE OR REPLACE TABLE
  `kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_option_features`
AS
WITH
-- ---------------------------------------------------------------------
-- Tunable parameters
-- ---------------------------------------------------------------------
params AS (
  SELECT
    7.0   AS halflife,         -- EWMA half-life in days
    1e-6  AS eps,              -- numerical floor for divides/logs
    -1.2  AS L,                -- log clamp lower bound
     1.2  AS U,                -- log clamp upper bound
    -- CVR (per-click)
    10.0  AS k_clicks,         -- pseudo-clicks for option CVR smoothing
     5.0  AS tau_orders,       -- shrink τ on orders (50% weight ≈5)
     2.0  AS min_ord_eff,      -- gate: if orders_eff_opt < 2 → fallback
    -- GPPI (per-impression)
    100.0 AS k_impr_opt,       -- pseudo-impressions for option GPPI smoothing
     50.0 AS tau_m1,           -- shrink τ on m1 evidence (50% weight ≈50)
     10.0 AS min_m1_eff        -- gate: if m1_eff_opt < 10 → fallback
),

-- ---------------------------------------------------------------------
-- Compute α_EWMA from half-life
-- α = 1 - 0.5^(1/HL)
-- ---------------------------------------------------------------------
alpha_ctx AS (
  SELECT
    halflife,
    1 - POW(0.5, 1/halflife) AS alpha_ewma,
    eps, L, U,
    k_clicks, tau_orders, min_ord_eff,
    k_impr_opt, tau_m1, min_m1_eff
  FROM params
),

-- ---------------------------------------------------------------------
-- Daily source: option-level orders and gross profit (m1)
-- ---------------------------------------------------------------------
src_opt AS (
  SELECT
    SAFE.PARSE_DATE('%Y-%m-%d', day) AS day_date,
    shown_deal                       AS deal_id,
    option_uuid                      AS option_id,
    ARRAY_TO_STRING(
      ARRAY(
        SELECT level
        FROM UNNEST([grt_l1, grt_l2, grt_l3, grt_l4, grt_l5, grt_l6]) AS level
        WHERE level IS NOT NULL AND TRIM(level) <> ''
      ),
      ' > '
    )                                AS category_path,
    SUM(sum_number_of_orders)        AS orders_day_opt,
    SUM(sum_m1_vfm)                  AS m1_day_opt
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.daily-search-relevance-dataset`
  WHERE shown_deal IS NOT NULL
  GROUP BY 1,2,3,4
),

-- ---------------------------------------------------------------------
-- Restrict to rolling 30-day window
-- ---------------------------------------------------------------------
win30 AS (
  SELECT * FROM src_opt
  WHERE day_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- ---------------------------------------------------------------------
-- EWMA smoothing of option-level evidence (orders, m1)
-- ---------------------------------------------------------------------
opt_idx AS (
  SELECT
    w.*,
    a.alpha_ewma,
    ROW_NUMBER() OVER (PARTITION BY w.deal_id, w.option_id ORDER BY w.day_date) AS rn,
    POW(1 - a.alpha_ewma, -ROW_NUMBER() OVER (PARTITION BY w.deal_id, w.option_id ORDER BY w.day_date)) AS decay_inv,
    POW(1 - a.alpha_ewma,  ROW_NUMBER() OVER (PARTITION BY w.deal_id, w.option_id ORDER BY w.day_date)) AS decay_pow
  FROM win30 w
  CROSS JOIN alpha_ctx a
),
opt_ewma AS (
  SELECT
    deal_id,
    option_id,
    category_path,
    day_date,
    -- EWMA effective orders and value
    alpha_ewma * decay_pow * SUM(orders_day_opt * decay_inv)
      OVER (PARTITION BY deal_id, option_id ORDER BY day_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_opt,
    alpha_ewma * decay_pow * SUM(m1_day_opt * decay_inv)
      OVER (PARTITION BY deal_id, option_id ORDER BY day_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS m1_eff_opt
  FROM opt_idx
),
opt_now AS (
  SELECT * FROM opt_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id, option_id ORDER BY day_date DESC) = 1
),

-- ---------------------------------------------------------------------
-- Aggregate option-level evidence per deal to compute sibling shares
-- ---------------------------------------------------------------------
opt_sum_per_deal AS (
  SELECT
    deal_id,
    SUM(orders_eff_opt) AS orders_eff_sum_deal,
    SUM(m1_eff_opt)     AS m1_eff_sum_deal
  FROM opt_now
  GROUP BY 1
),
opt_with_share AS (
  SELECT
    o.deal_id,
    o.option_id,
    o.category_path,
    o.orders_eff_opt,
    o.m1_eff_opt,
    s.orders_eff_sum_deal,
    s.m1_eff_sum_deal,
    SAFE_DIVIDE(o.orders_eff_opt, NULLIF(s.orders_eff_sum_deal, 0)) AS s_opt_orders, -- share by orders
    SAFE_DIVIDE(o.m1_eff_opt,     NULLIF(s.m1_eff_sum_deal,   0)) AS s_opt_value     -- share by value
  FROM opt_now o
  LEFT JOIN opt_sum_per_deal s USING (deal_id)
),

-- ---------------------------------------------------------------------
-- Parent DEAL metrics (clicks, impressions, CVR, GPPI, uplifts)
-- ---------------------------------------------------------------------
parent_deal AS (
  SELECT
    deal_id,
    category_path,
    clicks_eff_deal,
    impr_eff_deal,
    deal_cvr,
    gppi_deal,
    deal_cvr_coec_log_30d,
    deal_gppi_coec_log_30d
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features`
),

-- ---------------------------------------------------------------------
-- Combine option + parent data and compute observed vs expected metrics
-- ---------------------------------------------------------------------
opt_expect_observe AS (
  SELECT
    ow.deal_id,
    ow.option_id,
    COALESCE(ow.category_path, pd.category_path) AS category_path,

    -- Option evidence
    ow.orders_eff_opt,
    ow.m1_eff_opt,
    ow.s_opt_orders,
    ow.s_opt_value,

    -- Parent denominators
    pd.clicks_eff_deal,
    pd.impr_eff_deal,
    pd.deal_cvr,
    pd.gppi_deal,
    pd.deal_cvr_coec_log_30d,
    pd.deal_gppi_coec_log_30d,

    -- === CVR (per-click) ===
    (pd.deal_cvr * ow.s_opt_orders) AS m_opt_cvr,  -- expected per-click prob
    SAFE_DIVIDE(ow.orders_eff_opt, GREATEST(pd.clicks_eff_deal, a.eps)) AS p_hat_opt_cvr,
    SAFE_DIVIDE(ow.orders_eff_opt + (pd.deal_cvr * ow.s_opt_orders) * a.k_clicks,
                pd.clicks_eff_deal + a.k_clicks) AS cvr_opt,

    -- === GPPI (per-impression) ===
    (pd.gppi_deal * ow.s_opt_value) AS m_opt_gppi, -- expected gppi for option
    SAFE_DIVIDE(ow.m1_eff_opt, GREATEST(pd.impr_eff_deal, a.eps)) AS gppi_hat_opt,
    SAFE_DIVIDE(ow.m1_eff_opt + (pd.gppi_deal * ow.s_opt_value) * a.k_impr_opt,
                pd.impr_eff_deal + a.k_impr_opt) AS gppi_opt
  FROM opt_with_share ow
  LEFT JOIN parent_deal pd USING (deal_id)
  CROSS JOIN alpha_ctx a
),

-- ---------------------------------------------------------------------
-- Compute COEC (Observed / Expected) + log + clamp
-- ---------------------------------------------------------------------
opt_coec AS (
  SELECT
    oeo.*,
    -- CVR COEC
    SAFE_DIVIDE(oeo.cvr_opt,  GREATEST(oeo.m_opt_cvr,  a.eps)) AS coec_opt_cvr,
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(oeo.cvr_opt, GREATEST(oeo.m_opt_cvr,  a.eps)), a.eps))
    )) AS lg_coec_opt_cvr,
    -- GPPI COEC
    SAFE_DIVIDE(oeo.gppi_opt, GREATEST(oeo.m_opt_gppi, a.eps)) AS coec_opt_gppi,
    GREATEST(a.L, LEAST(a.U,
      LOG(GREATEST(SAFE_DIVIDE(oeo.gppi_opt, GREATEST(oeo.m_opt_gppi, a.eps)), a.eps))
    )) AS lg_coec_opt_gppi
  FROM opt_expect_observe oeo
  CROSS JOIN alpha_ctx a
),

-- ---------------------------------------------------------------------
-- Shrink log-COEC toward parent deal uplift
-- Two-step: compute weights first, then apply shrink/gate
-- ---------------------------------------------------------------------
blended_weights AS (
  SELECT
    oc.*,
    -- CVR weights
    a.tau_orders,
    a.min_ord_eff,
    SAFE_DIVIDE(oc.orders_eff_opt, oc.orders_eff_opt + a.tau_orders) AS w_opt_cvr,
    -- GPPI weights
    a.tau_m1,
    a.min_m1_eff,
    SAFE_DIVIDE(oc.m1_eff_opt, oc.m1_eff_opt + a.tau_m1) AS w_opt_gppi
  FROM opt_coec oc
  CROSS JOIN alpha_ctx a
),

blended AS (
  SELECT
    bw.*,
    -- Final log-COEC for CVR (option vs expected, shrunk to parent)
    CASE
      WHEN bw.orders_eff_opt < bw.min_ord_eff
        THEN bw.deal_cvr_coec_log_30d
      ELSE bw.w_opt_cvr * bw.lg_coec_opt_cvr
         + (1 - bw.w_opt_cvr) * bw.deal_cvr_coec_log_30d
    END AS option_cvr_coec_log_30d,
    -- Final log-COEC for GPPI
    CASE
      WHEN bw.m1_eff_opt < bw.min_m1_eff
        THEN bw.deal_gppi_coec_log_30d
      ELSE bw.w_opt_gppi * bw.lg_coec_opt_gppi
         + (1 - bw.w_opt_gppi) * bw.deal_gppi_coec_log_30d
    END AS option_gppi_coec_log_30d
  FROM blended_weights bw
)

-- ---------------------------------------------------------------------
-- Final projection (one row per (deal_id, option_id))
-- ---------------------------------------------------------------------
SELECT
  deal_id,
  option_id,
  category_path,

  -- === FINAL FEATURES ===
  option_cvr_coec_log_30d,
  option_gppi_coec_log_30d,

  -- === Diagnostics: CVR branch ===
  cvr_opt                      AS option_cvr,           -- smoothed per-click probability
  m_opt_cvr                    AS option_cvr_expected,  -- expected = deal_cvr * share
  coec_opt_cvr                 AS option_coec_cvr,      -- raw COEC
  lg_coec_opt_cvr,                                     -- log-COEC before shrink
  orders_eff_opt,
  clicks_eff_deal,
  s_opt_orders,
  w_opt_cvr,

  -- === Diagnostics: GPPI branch ===
  gppi_opt                     AS option_gppi,          -- smoothed profit per impression
  m_opt_gppi                   AS option_gppi_expected, -- expected = gppi_deal * share
  coec_opt_gppi                AS option_coec_gppi,     -- raw COEC
  lg_coec_opt_gppi,                                    -- log-COEC before shrink
  m1_eff_opt,
  impr_eff_deal,
  s_opt_value,
  w_opt_gppi,

  -- === Parent deal baselines ===
  deal_cvr,
  deal_cvr_coec_log_30d,
  deal_gppi_coec_log_30d

FROM blended;

