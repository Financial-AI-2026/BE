CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE extraction_run (
    id UUID PRIMARY KEY,
    model VARCHAR(100),
    prompt_version VARCHAR(50),
    input_condition VARCHAR(50),
    source_path TEXT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    metrics JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE etf_master (
    code VARCHAR(12) PRIMARY KEY,
    isin VARCHAR(12) UNIQUE,
    name VARCHAR(200) NOT NULL,
    market VARCHAR(2) NOT NULL CHECK (market IN ('KR', 'US')),
    manager VARCHAR(100),
    listed_at DATE,
    exchange VARCHAR(20),
    source VARCHAR(30) NOT NULL,
    display_order SMALLINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX etf_master_name_trgm ON etf_master USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX etf_master_display_order_unique
    ON etf_master (display_order)
    WHERE display_order IS NOT NULL;

CREATE TABLE etf_profile (
    code VARCHAR(12) PRIMARY KEY REFERENCES etf_master(code) ON DELETE CASCADE,
    base_index VARCHAR(200) NOT NULL,
    replication VARCHAR(10) NOT NULL CHECK (replication IN ('실물', '합성')),
    leverage NUMERIC(4, 2) NOT NULL,
    daily_rebalancing BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT false,
    strategy VARCHAR(20) NOT NULL CHECK (
        strategy IN ('지수추종', '레버리지', '인버스', '커버드콜', '자산혼합', '타겟데이트', '액티브', '기타')
    ),
    distribution VARCHAR(20) NOT NULL CHECK (
        distribution IN ('무분배', '월분배', '분기분배', '반기분배', '연분배')
    ),
    distribution_yield NUMERIC(5, 2),
    target_year SMALLINT,
    total_expense NUMERIC(5, 4) NOT NULL,
    fx_hedge VARCHAR(10) NOT NULL CHECK (fx_hedge IN ('헤지', '미헤지', '해당없음')),
    counterparty_risk BOOLEAN NOT NULL DEFAULT false,
    counterparty VARCHAR(200),
    main_assets TEXT[],
    is_complex_product BOOLEAN NOT NULL DEFAULT false,
    extracted_by VARCHAR(10) NOT NULL CHECK (extracted_by IN ('manual', 'ai')),
    extraction_run_id UUID REFERENCES extraction_run(id),
    reviewed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE evidence (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(12) NOT NULL REFERENCES etf_master(code) ON DELETE CASCADE,
    field VARCHAR(50),
    rule_code VARCHAR(20),
    quote TEXT NOT NULL,
    quote_original TEXT,
    location VARCHAR(200) NOT NULL,
    source_type VARCHAR(30) NOT NULL CHECK (
        source_type IN ('KR_PROSPECTUS', 'US_SUMMARY_PROSPECTUS')
    ),
    translated BOOLEAN NOT NULL DEFAULT false,
    display_order SMALLINT,
    CHECK (field IS NOT NULL OR rule_code IS NOT NULL)
);

CREATE INDEX evidence_code_rule ON evidence(code, rule_code);
CREATE INDEX evidence_code_field ON evidence(code, field);

CREATE TABLE etf_name_token (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(12) NOT NULL REFERENCES etf_master(code) ON DELETE CASCADE,
    seq SMALLINT NOT NULL,
    text VARCHAR(100),
    absent VARCHAR(20),
    translation TEXT NOT NULL,
    UNIQUE (code, seq),
    CHECK (text IS NOT NULL OR absent IS NOT NULL)
);

CREATE TABLE etf_hidden_insight (
    code VARCHAR(12) PRIMARY KEY REFERENCES etf_master(code) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    body TEXT NOT NULL
);

CREATE TABLE rule_config (
    code VARCHAR(20) PRIMARY KEY,
    level VARCHAR(10) NOT NULL CHECK (level IN ('warning', 'info', 'ok')),
    priority SMALLINT,
    category VARCHAR(20),
    summary TEXT NOT NULL,
    title TEXT,
    body TEXT NOT NULL,
    purpose_addon TEXT,
    widget_type VARCHAR(1)
);
