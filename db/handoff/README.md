# etf_profile 핸드오프

챗봇 개발용으로 넘기는 ETF 구조 데이터. `etf_profile_handoff.sql` 하나면 됩니다.

## 사용법

```bash
psql "$DATABASE_URL" -f etf_profile_handoff.sql
```

에러 없이 끝까지 실행되면 `etf_master` 8행, `etf_profile` 8행이 들어갑니다
(국내 6종 + 해외 2종: QYLD, TQQQ). 빈 DB에 직접 돌려서 확인 완료(2026-09-02).

`etf_profile.code`가 `etf_master.code`를 참조(FK)해서 두 테이블을 같이 넣었습니다.
`etf_profile.extraction_run_id`도 `extraction_run` 테이블을 참조하는데, 실제로 쓰는 값은
없어서(전부 NULL) 빈 테이블만 만들어둡니다.

## 필드가 뭘 뜻하는지

**`etf_master`** — 종목 기본 정보

| 필드 | 뜻 |
| :---- | :---- |
| `code` | 종목 코드 (국내는 6자리 숫자, 해외는 티커) |
| `market` | `KR` \| `US` |
| `source` | 이 종목 데이터를 누가 등록했는지 — 지금은 전부 `manual` (운영 스케줄러 없음) |

**`etf_profile`** — 위험구조 진단에 실제로 쓰이는 구조화 필드

| 필드 | 뜻 | 값 |
| :---- | :---- | :---- |
| `base_index` | 추종하는 기초지수 | 자유 텍스트 |
| `replication` | 복제방식 | `실물`(기초자산 직접 매수) \| `합성`(스왑·선물 계약) |
| `leverage` | 일일 목표 배율 | `1.00`이 일반 상품, `2.00`/`3.00`이 레버리지, 음수면 인버스 |
| `daily_rebalancing` | 매일 배율을 재조정하는 상품인지 | 레버리지·인버스만 `true` |
| `strategy` | 운용전략 유형 | `지수추종` \| `레버리지` \| `인버스` \| `커버드콜` \| `자산혼합` \| `타겟데이트` \| `액티브` \| `기타` |
| `distribution` | 분배주기 | `무분배` \| `월분배` \| `분기분배` \| `반기분배` \| `연분배` |
| `distribution_yield` | 연 환산 분배율(%) | 시장 데이터 기준, 투자설명서 원문 근거 아님 |
| `total_expense` | 총보수(%) | — |
| `fx_hedge` | 환헤지 여부 | `헤지` \| `미헤지` \| `해당없음`(국내 상품이라 환노출 자체가 없음) |
| `counterparty_risk` | 거래상대방 위험 존재 여부 | `합성` 복제 상품만 `true` |
| `main_assets` | 주요 편입자산 | 텍스트 배열 |
| `extracted_by` | 이 row가 AI 추출값인지 사람이 넣은 값인지 | `ai` \| `manual` — 아래 참고 |

## 주의할 것 — QYLD의 `distribution`

QYLD(`code = 'QYLD'`)만 `extracted_by = 'manual'`입니다. 나머지 7종은 AI가 투자설명서
원문에서 근거 문장과 함께 뽑은 값인데, QYLD는 SEC 요약투자설명서 원문 어디에도 분배주기를
직접 서술한 문장이 없어서 AI가 근거를 못 댔습니다 (`무분배`\~`연분배` 중 하나를 정해야 하는
스키마라 사람이 직접 확인해서 `월분배`로 넣어둔 값 — **값 자체는 맞지만(운용사 공식 공시로
재확인함), 투자설명서 원문 인용은 없습니다**).

챗봇이 "이 정보 어디서 나온 거예요?"류의 질문에 답할 때, QYLD의 분배주기만큼은 투자설명서
원문을 인용해서 답할 수 없다는 걸 감안해주세요. 상세 경위: 이 저장소의
`ctx/docs/OPEN_QUESTIONS.md` Q1-c, Q1-d.
