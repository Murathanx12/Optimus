---
id: aegis-finance-decisions
title: Aegis Finance — Decisions
tier: 2
type: decisions
project: aegis-finance
aliases:
- aegis-finance decisions
tags:
- project
- decisions
- expensive
sources:
- git:aegis-finance@9c2a0e5:docs/phase2_decisions.md
- git:aegis-finance@9c2a0e5:backend/db.py
- git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md
- git:aegis-finance@9c2a0e5:CLAUDE.md
source_root: ~\aegis-finance
status: active
created: '2026-06-03T08:04:40+00:00'
updated: '2026-06-03T08:04:40+00:00'
claims:
- id: aegis-finance-dec-000
  text: Build the ticker-to-sector map from three prioritized sources
  source: git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L5-L5
  status: active
  kind: decision
  rationale: cover large/mid-caps already in Aegis (config universe), the PI reference
    universe, and five small-cap biotech tickers from Murat's personal portfolio too
    small for either reference universe
  quote: '`real_analyzer._get_sector_map()` builds a ticker-to-sector mapping from
    three sources,'
- id: aegis-finance-dec-001
  text: Resolve user-added personal tickers' sectors via yfinance + a new ticker_metadata
    cache in Phase 5.5
  source: git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L34-L34
  status: active
  kind: decision
  rationale: otherwise unknown tickers return 'Other', so sector concentration flags
    misfire; it is a ~20-line addition, not a redesign
  quote: This is a ~20-line addition to the personal lane ingest path, not a redesign.
- id: aegis-finance-dec-002
  text: Defer the catalyst calendar and did-you-know panel to Phase 5 frontend rather
    than dropping them
  source: git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L40-L40
  status: active
  kind: decision
  rationale: catalyst data already exists via existing endpoints and the did-you-know
    raw data is already computed; only frontend narrative/compare logic remains
  quote: Both are **deferred to Phase 5 (frontend)**, not dropped.
- id: aegis-finance-dec-003
  text: Compute max drawdown inline from cumulative returns instead of delegating
    to drawdown_analyzer
  source: git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L54-L54
  status: active
  kind: decision
  rationale: the analyzer expects an absolute price series and returns a format needing
    conversion; the inline (cum/peak-1).min() is 4 lines, no conversion, and yields
    [-1,0] which MetricPack expects
  quote: Drawdown is computed inline from cumulative returns rather than delegating
    to
- id: aegis-finance-dec-004
  text: Use raw SQLite with WAL mode for the portfolio-intelligence persistence (not
    a heavier DB)
  source: git:aegis-finance@9c2a0e5:backend/db.py#L5-L5
  status: active
  kind: decision
  rationale: the rest of Aegis is stateless; persistence is needed only for paper-portfolio
    state, trade log, audit log, and personal decisions
  quote: Raw SQLite with WAL mode for the portfolio intelligence subsystem.
- id: aegis-finance-dec-005
  text: Use forward-only schema versioning with no Alembic
  source: git:aegis-finance@9c2a0e5:backend/db.py#L6-L6
  status: active
  kind: decision
  rationale: Alembic is overkill for 6 tables
  quote: Forward-only schema versioning (no Alembic — overkill for 6 tables).
- id: aegis-finance-dec-006
  text: Pick the final crash model per horizon by held-out Brier score
  source: git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L44-L44
  status: active
  kind: decision
  rationale: use whichever calibrates better on held-out data (typically LightGBM
    3m, Logistic 12m)
  quote: The final prediction is the model with better held-out Brier score (typically
    LightGBM for 3-month, Logistic for 12-month).
- id: aegis-finance-dec-007
  text: Validate with a walk-forward expanding window with purge gaps and periodic
    retrain
  source: git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L48-L48
  status: active
  kind: decision
  rationale: prevents data leakage; purge gaps 70/140/265 days for 3/6/12m, retrain
    every 252 days
  quote: '**Walk-forward expanding window** (no data leakage):'
- id: aegis-finance-dec-008
  text: Blend HMM regime probabilities into Monte Carlo drift and volatility at mixing
    weight 0.15
  source: git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L115-L115
  status: active
  kind: decision
  rationale: make the simulation regime-aware; weight is configurable
  quote: HMM regime probabilities blend into the Monte Carlo drift and volatility
    with a mixing weight of 0.15 (configurable).
- id: aegis-finance-dec-009
  text: Keep services stateless — no mutable global state except cache
  source: git:aegis-finance@9c2a0e5:CLAUDE.md#L201-L201
  status: active
  kind: decision
  rationale: stateless services; this is why only the portfolio-intelligence subsystem
    needs a database
  quote: Keep services stateless — no mutable global state except cache
- id: aegis-finance-dec-010
  text: Use purged CV with embargo for all ML validation
  source: git:aegis-finance@9c2a0e5:CLAUDE.md#L202-L202
  status: active
  kind: decision
  rationale: prevent leakage in financial ML (Lopez de Prado)
  quote: Use purged CV with embargo for all ML validation
- id: aegis-finance-dec-011
  text: Use walk-forward temporal splits, never random k-fold
  source: git:aegis-finance@9c2a0e5:CLAUDE.md#L203-L203
  status: active
  kind: decision
  rationale: financial data is temporal; random k-fold leaks future information
  quote: Use walk-forward temporal splits (never random k-fold)
- id: aegis-finance-dec-012
  text: Enforce monotonicity on multi-horizon crash predictions (3m <= 6m <= 12m)
  source: git:aegis-finance@9c2a0e5:CLAUDE.md#L205-L205
  status: active
  kind: decision
  rationale: longer horizons must carry at least as much crash probability
  quote: Enforce monotonicity on multi-horizon predictions (3m ≤ 6m ≤ 12m)
---

# Aegis Finance — Decisions

> Distilled decision-claims (LLM-extracted, with rationale + source quote).

## Build the ticker-to-sector map from three prioritized sources

- **Why:** cover large/mid-caps already in Aegis (config universe), the PI reference universe, and five small-cap biotech tickers from Murat's personal portfolio too small for either reference universe
- **Source:** `git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L5-L5`
- **Quote:** “`real_analyzer._get_sector_map()` builds a ticker-to-sector mapping from three sources,”

## Resolve user-added personal tickers' sectors via yfinance + a new ticker_metadata cache in Phase 5.5

- **Why:** otherwise unknown tickers return 'Other', so sector concentration flags misfire; it is a ~20-line addition, not a redesign
- **Source:** `git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L34-L34`
- **Quote:** “This is a ~20-line addition to the personal lane ingest path, not a redesign.”

## Defer the catalyst calendar and did-you-know panel to Phase 5 frontend rather than dropping them

- **Why:** catalyst data already exists via existing endpoints and the did-you-know raw data is already computed; only frontend narrative/compare logic remains
- **Source:** `git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L40-L40`
- **Quote:** “Both are **deferred to Phase 5 (frontend)**, not dropped.”

## Compute max drawdown inline from cumulative returns instead of delegating to drawdown_analyzer

- **Why:** the analyzer expects an absolute price series and returns a format needing conversion; the inline (cum/peak-1).min() is 4 lines, no conversion, and yields [-1,0] which MetricPack expects
- **Source:** `git:aegis-finance@9c2a0e5:docs/phase2_decisions.md#L54-L54`
- **Quote:** “Drawdown is computed inline from cumulative returns rather than delegating to”

## Use raw SQLite with WAL mode for the portfolio-intelligence persistence (not a heavier DB)

- **Why:** the rest of Aegis is stateless; persistence is needed only for paper-portfolio state, trade log, audit log, and personal decisions
- **Source:** `git:aegis-finance@9c2a0e5:backend/db.py#L5-L5`
- **Quote:** “Raw SQLite with WAL mode for the portfolio intelligence subsystem.”

## Use forward-only schema versioning with no Alembic

- **Why:** Alembic is overkill for 6 tables
- **Source:** `git:aegis-finance@9c2a0e5:backend/db.py#L6-L6`
- **Quote:** “Forward-only schema versioning (no Alembic — overkill for 6 tables).”

## Pick the final crash model per horizon by held-out Brier score

- **Why:** use whichever calibrates better on held-out data (typically LightGBM 3m, Logistic 12m)
- **Source:** `git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L44-L44`
- **Quote:** “The final prediction is the model with better held-out Brier score (typically LightGBM for 3-month, Logistic for 12-month).”

## Validate with a walk-forward expanding window with purge gaps and periodic retrain

- **Why:** prevents data leakage; purge gaps 70/140/265 days for 3/6/12m, retrain every 252 days
- **Source:** `git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L48-L48`
- **Quote:** “**Walk-forward expanding window** (no data leakage):”

## Blend HMM regime probabilities into Monte Carlo drift and volatility at mixing weight 0.15

- **Why:** make the simulation regime-aware; weight is configurable
- **Source:** `git:aegis-finance@9c2a0e5:docs/METHODOLOGY.md#L115-L115`
- **Quote:** “HMM regime probabilities blend into the Monte Carlo drift and volatility with a mixing weight of 0.15 (configurable).”

## Keep services stateless — no mutable global state except cache

- **Why:** stateless services; this is why only the portfolio-intelligence subsystem needs a database
- **Source:** `git:aegis-finance@9c2a0e5:CLAUDE.md#L201-L201`
- **Quote:** “Keep services stateless — no mutable global state except cache”

## Use purged CV with embargo for all ML validation

- **Why:** prevent leakage in financial ML (Lopez de Prado)
- **Source:** `git:aegis-finance@9c2a0e5:CLAUDE.md#L202-L202`
- **Quote:** “Use purged CV with embargo for all ML validation”

## Use walk-forward temporal splits, never random k-fold

- **Why:** financial data is temporal; random k-fold leaks future information
- **Source:** `git:aegis-finance@9c2a0e5:CLAUDE.md#L203-L203`
- **Quote:** “Use walk-forward temporal splits (never random k-fold)”

## Enforce monotonicity on multi-horizon crash predictions (3m <= 6m <= 12m)

- **Why:** longer horizons must carry at least as much crash probability
- **Source:** `git:aegis-finance@9c2a0e5:CLAUDE.md#L205-L205`
- **Quote:** “Enforce monotonicity on multi-horizon predictions (3m ≤ 6m ≤ 12m)”
