---
id: aegis-finance-overview
title: Aegis Finance — Overview
tier: 2
type: overview
project: aegis-finance
aliases:
- aegis-finance
- Aegis Finance
- aegis
tags:
- project
- overview
sources:
- git:aegis-finance@bb47895:README.md
- git:aegis-finance@bb47895:ABSTRACT.md
source_root: ~\aegis-finance
status: active
created: '2026-07-10T16:18:37+00:00'
updated: '2026-07-10T16:18:37+00:00'
claims:
- id: aegis-finance-desc
  text: Free, open-source market intelligence platform combining ML crash prediction,
    Monte Carlo simulation, and portfolio construction in a web dashboard.
  source: git:aegis-finance@bb47895:README.md#L3-L3
  status: active
- id: aegis-finance-cap-00
  text: '**Crash Probability** — LightGBM + Logistic Regression blend predicting 20%+
    drawdown probability over 3, 6, and 12-month horizons. Validated with purged cross-validation
    and walk-forward backtesting (3m Brier score: 0.046; see [Known Limitations](#known-limitations)
    for horizon accuracy details).'
  source: git:aegis-finance@bb47895:README.md#L9-L9
  status: active
- id: aegis-finance-cap-01
  text: '**Monte Carlo Projections** — Jump-diffusion simulation (Merton 1976) with
    GJR-GARCH volatility, Student-t innovations, and antithetic variates. 10,000 paths
    default. Validated against Goldman Sachs, JPMorgan, and Vanguard 10-year return
    assumptions ([docs/REALITY_CHECK.md](docs/REALITY_CHECK.md)).'
  source: git:aegis-finance@bb47895:README.md#L10-L10
  status: active
- id: aegis-finance-cap-02
  text: '**Portfolio Builder** — Black-Litterman, Hierarchical Risk Parity (HRP),
    and template methods with Ledoit-Wolf covariance shrinkage. 5 goal profiles (preservation,
    income, growth, aggressive growth, retirement). Uses sector ETFs, not individual
    stock selection.'
  source: git:aegis-finance@bb47895:README.md#L11-L11
  status: active
- id: aegis-finance-cap-03
  text: '**Macro Risk Dashboard** — 9-factor composite risk score from FRED data (yield
    curve, NFCI, initial claims, VIX, credit spreads, etc.) with regime classification
    (Bull/Bear/Volatile/Neutral).'
  source: git:aegis-finance@bb47895:README.md#L12-L12
  status: active
- id: aegis-finance-cap-04
  text: '**Stock Analysis** — Per-ticker Monte Carlo projections with beta-adjusted
    crash frequency, analyst target blending, and SHAP explainability showing which
    factors drive each prediction.'
  source: git:aegis-finance@bb47895:README.md#L13-L13
  status: active
- id: aegis-finance-cap-05
  text: '**Stock Screener** — 30+ stocks with Buy/Hold/Sell signals, Sharpe ratios,
    and sector filtering.'
  source: git:aegis-finance@bb47895:README.md#L14-L14
  status: active
- id: aegis-finance-cap-06
  text: '**Sector Analysis** — 11 S&P 500 sectors ranked by risk-adjusted expected
    return.'
  source: git:aegis-finance@bb47895:README.md#L15-L15
  status: active
- id: aegis-finance-cap-07
  text: '**News Intelligence** — GDELT event scoring with FinBERT sentiment analysis
    and optional DeepSeek AI summaries.'
  source: git:aegis-finance@bb47895:README.md#L16-L16
  status: active
- id: aegis-finance-cap-08
  text: '**Retirement Planner** — Compound growth projections with inflation adjustment.'
  source: git:aegis-finance@bb47895:README.md#L17-L17
  status: active
- id: aegis-finance-cap-09
  text: '**Net Liquidity Tracker** — Fed balance sheet (WALCL - TGA - RRP) as a market
    indicator.'
  source: git:aegis-finance@bb47895:README.md#L18-L18
  status: active
- id: aegis-finance-cap-10
  text: '**Data Quality Monitoring** — Automated staleness, range, and completeness
    checks.'
  source: git:aegis-finance@bb47895:README.md#L19-L19
  status: active
- id: aegis-finance-cap-11
  text: '**External Validation** — Cross-checks crash predictions against LEI, SLOOS,
    Fed Funds, and Consumer Sentiment.'
  source: git:aegis-finance@bb47895:README.md#L20-L20
  status: active
---

# Aegis Finance

> Free, open-source market intelligence platform combining ML crash prediction, Monte Carlo simulation, and portfolio construction in a web dashboard.

## Capabilities

- **Crash Probability** — LightGBM + Logistic Regression blend predicting 20%+ drawdown probability over 3, 6, and 12-month horizons. Validated with purged cross-validation and walk-forward backtesting (3m Brier score: 0.046; see [Known Limitations](#known-limitations) for horizon accuracy details).
- **Monte Carlo Projections** — Jump-diffusion simulation (Merton 1976) with GJR-GARCH volatility, Student-t innovations, and antithetic variates. 10,000 paths default. Validated against Goldman Sachs, JPMorgan, and Vanguard 10-year return assumptions ([docs/REALITY_CHECK.md](docs/REALITY_CHECK.md)).
- **Portfolio Builder** — Black-Litterman, Hierarchical Risk Parity (HRP), and template methods with Ledoit-Wolf covariance shrinkage. 5 goal profiles (preservation, income, growth, aggressive growth, retirement). Uses sector ETFs, not individual stock selection.
- **Macro Risk Dashboard** — 9-factor composite risk score from FRED data (yield curve, NFCI, initial claims, VIX, credit spreads, etc.) with regime classification (Bull/Bear/Volatile/Neutral).
- **Stock Analysis** — Per-ticker Monte Carlo projections with beta-adjusted crash frequency, analyst target blending, and SHAP explainability showing which factors drive each prediction.
- **Stock Screener** — 30+ stocks with Buy/Hold/Sell signals, Sharpe ratios, and sector filtering.
- **Sector Analysis** — 11 S&P 500 sectors ranked by risk-adjusted expected return.
- **News Intelligence** — GDELT event scoring with FinBERT sentiment analysis and optional DeepSeek AI summaries.
- **Retirement Planner** — Compound growth projections with inflation adjustment.
- **Net Liquidity Tracker** — Fed balance sheet (WALCL - TGA - RRP) as a market indicator.
- **Data Quality Monitoring** — Automated staleness, range, and completeness checks.
- **External Validation** — Cross-checks crash predictions against LEI, SLOOS, Fed Funds, and Consumer Sentiment.

## README sections

- What It Does
- What It Is Not
- Comparison to Similar Projects
- Known Limitations
- Quick Start
- Prerequisites
- Setup
- Train the Crash Model (optional, ~5-10 min)
- Docker
- Commands Reference
- Development
- Testing
- ML Engine (Offline)
- Docker
- API Endpoints
- API Testing (curl)
- Data Sources
- API Keys
- Tech Stack
- Architecture
- Deployment
- Project Structure
- Methodology Status
- Built With / References
- Research & Validation
- Free Hosting
- Contributing
- Disclaimer
- License
