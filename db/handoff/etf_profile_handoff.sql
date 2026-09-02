-- etf_profile 핸드오프용 최소 마이그레이션 + 데이터
--
-- 목적: 챗봇 개발 담당자가 별도 서비스/DB에서 바로 실행해 etf_master + etf_profile
-- 2개 테이블을 그대로 재현할 수 있게 하기 위한 자족(self-contained) SQL 파일.
-- 전체 스키마(app/db/migration/V2__create_etf_diagnosis_schema.sql)의 부분집합이며,
-- 스냅샷 시점: 2026-09-02, 데이터는 8종(국내 6 + 해외 2) 전체.
--
-- 실행 방법: psql "$DATABASE_URL" -f db/handoff/etf_profile_handoff.sql
--
-- 주의:
-- 1. etf_profile.code가 etf_master.code를 참조(FK)하므로 etf_master도 함께 포함했다.
--    "etf_profile만 필요하다"고 해도 이 FK 때문에 etf_master 없이는 etf_profile을
--    생성/적재할 수 없다.
-- 2. etf_profile.extraction_run_id가 extraction_run(id)을 참조하므로 그 테이블도
--    최소 형태로 만들어둔다 (실제 사용 데이터는 없음 — 8종 전부 extraction_run_id NULL).
-- 3. CREATE EXTENSION은 DB에 슈퍼유저/확장 생성 권한이 있어야 한다. 관리형 Postgres라
--    권한이 없으면 이 줄만 인프라 담당에게 별도 요청하고 나머지는 그대로 실행하면 된다.
-- 4. extracted_by = 'ai' | 'manual' 구분에 대해서는 `ctx/docs/OPEN_QUESTIONS.md` Q1-c 참고.
--    QYLD만 'manual' — SEC 요약투자설명서 원문에 분배주기 서술이 없어 fail-closed 원칙상
--    AI 추출을 신뢰하지 않기로 함.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS extraction_run (
    id UUID PRIMARY KEY,
    model VARCHAR(100),
    prompt_version VARCHAR(50),
    input_condition VARCHAR(50),
    source_path TEXT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
    metrics JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS etf_master (
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

CREATE INDEX IF NOT EXISTS etf_master_name_trgm ON etf_master USING gin (name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS etf_master_display_order_unique
    ON etf_master (display_order)
    WHERE display_order IS NOT NULL;

CREATE TABLE IF NOT EXISTS etf_profile (
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

-- === 데이터 (2026-09-02 DB 스냅샷, 8종) ===

INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('102110', NULL, 'TIGER 200', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 6, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('133690', NULL, 'TIGER 미국나스닥100', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 4, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('418660', NULL, 'TIGER 미국나스닥100레버리지(합성)', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 1, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('435420', NULL, 'TIGER 미국나스닥100채권혼합50', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 3, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('441680', NULL, 'TIGER 미국나스닥100커버드콜(합성)', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 2, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('448290', NULL, 'TIGER 미국S&P500(H)', 'KR', '미래에셋자산운용', NULL, NULL, 'manual', 5, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('QYLD', NULL, 'Global X NASDAQ 100 Covered Call ETF', 'US', 'Global X', NULL, 'NASDAQ', 'manual', 8, '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_master (code, isin, name, market, manager, listed_at, exchange, source, display_order, updated_at) VALUES ('TQQQ', NULL, 'ProShares UltraPro QQQ', 'US', 'ProShares', NULL, 'NASDAQ', 'manual', 7, '2026-09-02 12:35:53.892255+00');

INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('102110', '코스피200', '실물', 1.00, false, false, '지수추종', '분기분배', 2.00, NULL, 0.0500, '해당없음', false, NULL, '{"국내 주식"}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('133690', 'NASDAQ-100', '실물', 1.00, false, false, '지수추종', '분기분배', 0.50, NULL, 0.0068, '미헤지', false, NULL, '{"미국 기술주"}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('418660', 'NASDAQ-100', '합성', 2.00, true, false, '레버리지', '연분배', 0.80, NULL, 0.2500, '미헤지', true, '미래에셋증권·한국투자증권·NH투자증권·KB증권·삼성증권·신한금융투자·메리츠증권·키움증권', '{"미국 기술주",파생상품}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('435420', '나스닥100 + 국내채권 혼합 (5:5)', '실물', 1.00, false, false, '자산혼합', '분기분배', 1.50, NULL, 0.2500, '미헤지', false, NULL, '{주식,채권}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('441680', 'Cboe Nasdaq-100 BuyWrite V2 (TR)', '합성', 1.00, false, false, '커버드콜', '월분배', 12.30, NULL, 0.3700, '미헤지', true, '미래에셋증권·한국투자증권·NH투자증권·KB증권·삼성증권·신한금융투자·메리츠증권·키움증권', '{"NASDAQ-100 포트폴리오",콜옵션}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('448290', 'S&P 500', '실물', 1.00, false, false, '지수추종', '분기분배', 1.00, NULL, 0.0700, '헤지', false, NULL, '{"미국 주식"}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('QYLD', 'Cboe NASDAQ-100 BuyWrite V2', '실물', 1.00, false, false, '커버드콜', '월분배', 11.50, NULL, 0.6000, '미헤지', false, NULL, '{"NASDAQ 100","Covered Call"}', false, 'manual', NULL, '2026-08-30 15:00:00+00', '2026-09-02 12:35:53.892255+00');
INSERT INTO etf_profile (code, base_index, replication, leverage, daily_rebalancing, is_active, strategy, distribution, distribution_yield, target_year, total_expense, fx_hedge, counterparty_risk, counterparty, main_assets, is_complex_product, extracted_by, extraction_run_id, reviewed_at, updated_at) VALUES ('TQQQ', 'Nasdaq-100', '합성', 3.00, true, false, '레버리지', '분기분배', 0.50, NULL, 0.8200, '미헤지', true, NULL, '{"스왑 계약","선물 계약"}', false, 'ai', NULL, '2026-09-01 15:00:00+00', '2026-09-02 12:35:53.892255+00');

COMMIT;
