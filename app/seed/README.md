# Seed Data

MVP data is loaded from JSON files in this directory.

```text
app/seed/
├── etfs/
│   ├── 418660.json
│   └── ...
├── rules.json
└── load.py
```

Run:

```bash
uv run python -m app.seed.load
```

ETF seed files must copy values and copy text from `MVP_테스트데이터_ETF8종.md` without
rewriting product copy. The loader rejects profile rows without `reviewed_at`, because
unreviewed extraction output must not be exposed by API handlers.

Minimal ETF file shape:

```json
{
  "master": {
    "code": "418660",
    "isin": null,
    "name": "정본 문서에서 복사",
    "market": "KR",
    "manager": "미래에셋자산운용",
    "source": "manual",
    "display_order": 1
  },
  "profile": {
    "base_index": "정본 문서에서 복사",
    "replication": "합성",
    "leverage": 2.0,
    "daily_rebalancing": true,
    "is_active": false,
    "strategy": "레버리지",
    "distribution": "연분배",
    "distribution_yield": 0.8,
    "target_year": null,
    "total_expense": 0.25,
    "fx_hedge": "미헤지",
    "counterparty_risk": true,
    "counterparty": null,
    "main_assets": [],
    "is_complex_product": false,
    "extracted_by": "manual",
    "reviewed_at": "2026-08-31T00:00:00+09:00"
  },
  "tokens": [],
  "hiddenInsight": null,
  "evidence": []
}
```
