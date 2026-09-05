CREATE TABLE chat_suggested_question (
    id BIGSERIAL PRIMARY KEY,
    code VARCHAR(12) REFERENCES etf_master(code) ON DELETE CASCADE,
    stage VARCHAR(2) NOT NULL CHECK (stage IN ('S4', 'S6')),
    seq SMALLINT NOT NULL,
    question TEXT NOT NULL,
    CHECK ((stage = 'S4' AND code IS NOT NULL) OR (stage = 'S6' AND code IS NULL))
);

-- S4: 종목별 최대 3개, 종목당 순서 유일
CREATE UNIQUE INDEX chat_suggested_question_product_unique
    ON chat_suggested_question (code, seq)
    WHERE code IS NOT NULL;

-- S6: 종목 공통, 순서 유일
CREATE UNIQUE INDEX chat_suggested_question_common_unique
    ON chat_suggested_question (stage, seq)
    WHERE code IS NULL;
