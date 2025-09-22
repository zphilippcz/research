-- =====================================================================
-- Option CVR-COEC (30d, global) with shrink → DEAL uplift
-- Output: kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_option_features
--
-- Intuition:
--   * We do not have option-level clicks (option_uuid is non-null only when ordered).
--   * We therefore model option as a *split* of the deal CVR:
--       O (observed)   : p_hat_opt = orders_eff_opt / clicks_eff_deal(parent)
--       E (expected)   : m_opt     = deal_cvr(parent) * s_opt,
--                        where s_opt is the EWMA share of this option's orders among sibling options.
--       COEC_opt       : p_hat_opt / max(m_opt, eps)
--   * We log-transform & clamp, then shrink toward the parent deal uplift:
--       lg_final = w_opt * lg_opt + (1 - w_opt) * deal_cvr_coec_log_30d(parent)
--     with a low-data gate: if orders_eff_opt < MIN_ORD_eff → fallback to parent uplift.
--
-- Dependencies:
--   * Requires the previously built DEAL table:
--       kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features
--     (we use: deal_id, category_path, clicks_eff_deal, deal_cvr, deal_cvr_coec_log_30d)
--
-- Why this is sound:
--   * For a given deal, options are mutually exclusive outcomes of a click.
--   * Sum_opt p_hat_opt ≈ deal_cvr; distributing E via the order share s_opt keeps consistency.
--   * Shrinking to the parent deal uplift preserves signal where option evidence is sparse.
-- =====================================================================

CREATE OR REPLACE TABLE
  `kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_option_features`
AS
-- --------------------------
-- Tunable parameters (option layer)
-- --------------------------
WITH
params AS (
  SELECT
    7.0  AS halflife,          -- EWMA half-life in days (align with deal; can tune independently)
    1e-6 AS eps,               -- numerical floor for divides/logs
    -1.2 AS L,                 -- log clamp low
     1.2 AS U,                 -- log clamp high
    10.0 AS k_clicks,          -- prior strength in "per-click" smoothing at option level
     5.0 AS tau_orders,        -- shrink τ on option evidence (orders); 50% weight at ~5 eff. orders
     2.0 AS min_ord_eff        -- gate: if orders_eff_opt < 2 → fallback to parent uplift
),

-- --------------------------
-- α_EWMA from half-life
-- --------------------------
alpha_ctx AS (
  SELECT
    halflife,
    1 - POW(0.5, 1/halflife) AS alpha_ewma,
    eps, L, U, k_clicks, tau_orders, min_ord_eff
  FROM params
),

-- --------------------------
-- Source (daily), we only need orders per option; clicks are taken from the DEAL parent
-- --------------------------
src_opt AS (
  SELECT
    SAFE.PARSE_DATE('%Y-%m-%d', day)                                       AS day_date,
    shown_deal                                                              AS deal_id,
    option_uuid                                                             AS option_id,
    -- build category_path for completeness/debug; for joins we rely on deal table
    ARRAY_TO_STRING(
      ARRAY(
        SELECT level
        FROM UNNEST([grt_l1, grt_l2, grt_l3, grt_l4, grt_l5, grt_l6]) AS level
        WHERE level IS NOT NULL AND TRIM(level) <> ''
      ),
      ' > '
    )                                                                       AS category_path,
    SUM(sum_number_of_orders)                                               AS orders_day_opt
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.daily-search-relevance-dataset`
  WHERE shown_deal IS NOT NULL
  GROUP BY 1,2,3,4
),

-- --------------------------
-- Restrict to rolling 30 days
-- --------------------------
win30 AS (
  SELECT * FROM src_opt
  WHERE day_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- --------------------------
-- EWMA orders on OPTION level (evidence for that option)
-- --------------------------
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
    alpha_ewma * decay_pow * SUM(orders_day_opt * decay_inv)
      OVER (PARTITION BY deal_id, option_id ORDER BY day_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS orders_eff_opt
  FROM opt_idx
),
opt_now AS (
  -- one row per (deal_id, option_id) as of today
  SELECT * FROM opt_ewma
  QUALIFY ROW_NUMBER() OVER (PARTITION BY deal_id, option_id ORDER BY day_date DESC) = 1
),

-- --------------------------
-- Aggregate option evidence per deal to form order shares s_opt
-- --------------------------
opt_sum_per_deal AS (
  SELECT
    deal_id,
    SUM(orders_eff_opt) AS orders_eff_sum_deal
  FROM opt_now
  GROUP BY 1
),

opt_with_share AS (
  SELECT
    o.deal_id,
    o.option_id,
    o.category_path,
    o.orders_eff_opt,
    s.orders_eff_sum_deal,
    SAFE_DIVIDE(o.orders_eff_opt, NULLIF(s.orders_eff_sum_deal, 0)) AS s_opt   -- EWMA order share
  FROM opt_now o
  LEFT JOIN opt_sum_per_deal s USING (deal_id)
),

-- --------------------------
-- Bring parent DEAL metrics (from deal_features)
-- We need: clicks_eff_deal (denominator for per-click probability),
--          deal_cvr (expected per-click conversion prob for the deal),
--          deal_cvr_coec_log_30d (parent uplift for shrink baseline).
-- --------------------------
parent_deal AS (
  SELECT
    deal_id,
    category_path,
    clicks_eff_deal,
    deal_cvr,                   -- from your deal_features: smoothed deal CVR
    deal_cvr_coec_log_30d       -- parent uplift (log-COEC after shrink)
  FROM `kbc-grpn-40-0cd2.out_c_search_relavance_ML.deal_features`
),

-- --------------------------
-- Expected vs Observed on option:
--   Expected m_opt = deal_cvr(parent) * s_opt
--   Observed  p_hat = orders_eff_opt / clicks_eff_deal(parent)
--   Smooth per-click probability with weak prior k_clicks centered at m_opt:
--     cvr_opt = (orders_eff_opt + m_opt*k) / (clicks_eff_deal + k)
-- --------------------------
opt_expect_observe AS (
  SELECT
    ow.deal_id,
    ow.option_id,
    COALESCE(ow.category_path, pd.category_path) AS category_path,
    ow.orders_eff_opt,
    ow.s_opt,
    pd.clicks_eff_deal,
    pd.deal_cvr,
    pd.deal_cvr_coec_log_30d,
    -- expected option per-click probability
    (pd.deal_cvr * ow.s_opt) AS m_opt,
    -- observed per-click probability
    SAFE_DIVIDE(ow.orders_eff_opt, GREATEST(pd.clicks_eff_deal, a.eps)) AS p_hat_opt,
    -- smoothed per-click CVR for option
    SAFE_DIVIDE(ow.orders_eff_opt + (pd.deal_cvr * ow.s_opt) * a.k_clicks,
                pd.clicks_eff_deal + a.k_clicks) AS cvr_opt
  FROM opt_with_share ow
  LEFT JOIN parent_deal pd USING (deal_id)
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- Option COEC, log + clamp
-- --------------------------
opt_coec AS (
  SELECT
    oeo.*,
    SAFE_DIVIDE(oeo.cvr_opt, GREATEST(oeo.m_opt, a.eps)) AS coec_opt,
    GREATEST(a.L,
      LEAST(a.U,
        LOG(GREATEST(
          SAFE_DIVIDE(oeo.cvr_opt, GREATEST(oeo.m_opt, a.eps)),
          a.eps
        ))
      )
    ) AS lg_coec_opt
  FROM opt_expect_observe oeo
  CROSS JOIN alpha_ctx a
),

-- --------------------------
-- Shrink to parent DEAL uplift:
--   Evidence for option = orders_eff_opt (since clicks are only on parent).
--   w_opt = orders_eff_opt / (orders_eff_opt + tau_orders)
--   Gate: if orders_eff_opt < min_ord_eff → fallback to parent uplift.
-- --------------------------
blended AS (
  SELECT
    oc.*,
    a.tau_orders,
    a.min_ord_eff,
    SAFE_DIVIDE(oc.orders_eff_opt, oc.orders_eff_opt + a.tau_orders) AS w_opt,
    CASE
      WHEN oc.orders_eff_opt < a.min_ord_eff
        THEN oc.deal_cvr_coec_log_30d
      ELSE oc.w_opt * oc.lg_coec_opt + (1 - oc.w_opt) * oc.deal_cvr_coec_log_30d
    END AS option_cvr_coec_log_30d
  FROM opt_coec oc
  CROSS JOIN alpha_ctx a
)

-- =========================
-- Final projection (one row per (deal_id, option_id))
-- =========================
SELECT
  deal_id,
  option_id,
  category_path,

  -- FINAL FEATURE: log-COEC for option after shrink/gate (baseline = parent deal uplift)
  option_cvr_coec_log_30d,

  -- Non-log and components (useful diagnostics)
  cvr_opt                      AS option_cvr,          -- smoothed per-click prob for this option
  m_opt                        AS option_cvr_expected, -- expected per-click prob = deal_cvr * share
  coec_opt                     AS option_coec,         -- non-log COEC (option vs expected)
  lg_coec_opt,                                        -- raw log-COEC before shrink

  -- Evidence & weights
  orders_eff_opt,
  clicks_eff_deal,
  s_opt                        AS option_order_share,  -- EWMA share among siblings
  w_opt,

  -- Parent baselines
  deal_cvr,
  deal_cvr_coec_log_30d

FROM blended;
