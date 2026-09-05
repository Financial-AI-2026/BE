CREATE TABLE rule_config_variant (
    id BIGSERIAL PRIMARY KEY,
    rule_code VARCHAR(20) NOT NULL REFERENCES rule_config(code) ON DELETE CASCADE,
    purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('CAPITAL_GAIN', 'INCOME', 'GROWTH')),
    summary TEXT NOT NULL,
    title TEXT,
    body TEXT NOT NULL,
    UNIQUE (rule_code, purpose)
);
