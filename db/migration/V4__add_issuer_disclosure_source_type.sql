-- Q10 (ctx/docs/OPEN_QUESTIONS.md): 근거 출처 정책에 예외를 하나 추가한다.
--
-- 기본 원칙은 그대로("근거 = 투자설명서 원문")지만, 분배주기(distribution)·총보수
-- (totalExpense)처럼 운용 실적에 따라 달라지는 값은 애초에 투자설명서에 실리지 않는
-- 게 정상이라, 운용사의 "법정 공시 의무에 따라 작성되는 영역"(지급기준일·금액 등을
-- 법적으로 공시하는 자료 — 운용사가 임의로 쓰는 홍보/마케팅 문구와는 구분)을
-- 근거 출처로 추가 인정하기로 했다.

ALTER TABLE evidence DROP CONSTRAINT evidence_source_type_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_source_type_check CHECK (
    source_type IN ('KR_PROSPECTUS', 'US_SUMMARY_PROSPECTUS', 'ISSUER_DISCLOSURE')
);
