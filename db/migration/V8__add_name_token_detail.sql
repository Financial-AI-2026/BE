-- 이름 해독 토큰의 "상세 설명"(F-S4-02, 펼치기 카드) 추가.
--
-- etf_name_token.translation은 F-S4-01(좌우 대조)에 쓰이는 "한 줄 번역"만 담고
-- 있었다. 정본 문서(ctx/docs/[최종]MVP_테스트데이터_ETF8종.md §2)에는 토큰마다
-- 한 줄 번역과는 별개인 2~3문장짜리 "상세 설명"이 함께 정의돼 있는데, 그 컬럼이
-- 스키마 설계 때(docs/02 §3-4) 빠졌다. 그 결과 FE가 상세 설명 자리에도 translation을
-- 재사용해 "TIGER · 미래에셋이 만든 · 미래에셋이 만든"처럼 같은 문구가 중복 표시됐다.
--
-- 정본 문서 §2의 "상세 설명" 컬럼을 한 글자도 고치지 않고 그대로 옮긴다 (CLAUDE.md §3-4).
-- 예외 하나: 102110(TIGER 200) seq2 원문이 "삼성전자, 삼성전자 같은 기업이..."로
-- 코스피200 예시 기업명이 중복된 오탈자였다 — 기획 확인 후 "삼성전자, SK하이닉스,
-- 현대차"로 정정. 정본 문서(ctx/docs)에도 동일하게 반영했다.

ALTER TABLE etf_name_token ADD COLUMN detail TEXT;

UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '102110' AND seq = 1;
UPDATE etf_name_token SET detail = '코스피에 상장된 대표 기업 200개를 묶은 ''코스피200'' 지수를 뜻해요. 삼성전자, SK하이닉스, 현대차 같은 기업이 여기에 포함돼 있어요. 이 지수를 그대로 따라가는 단순한 구조예요.' WHERE code = '102110' AND seq = 2;
UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '133690' AND seq = 1;
UPDATE etf_name_token SET detail = '미국 나스닥 시장의 기술 중심 대형기업 100개를 묶은 지수예요. 애플, 마이크로소프트, 엔비디아 같은 기업이 포함돼 있어요. 이 상품은 그 지수를 그대로 따라가요.' WHERE code = '133690' AND seq = 2;
UPDATE etf_name_token SET detail = '이름에 (H)가 없어요. 환율 변동을 막아주는 장치가 없다는 뜻이라, 미국 주가가 올라도 원달러 환율이 떨어지면 손해를 볼 수 있어요.' WHERE code = '133690' AND seq = 3;
UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '418660' AND seq = 1;
UPDATE etf_name_token SET detail = '미국 나스닥 시장에 상장된 기술 중심 대형기업 100개를 묶은 지수예요. 애플, 마이크로소프트, 엔비디아 같은 기업이 여기에 포함돼 있어요.' WHERE code = '418660' AND seq = 2;
UPDATE etf_name_token SET detail = '지수가 하루에 1% 오르면 이 ETF는 2% 올라요. 반대로 내려가면 2%가 내려가요. 이 2배는 하루 단위로 계산돼요.' WHERE code = '418660' AND seq = 3;
UPDATE etf_name_token SET detail = '실제로 나스닥100 주식을 직접 사는 게 아니라 증권사와 계약을 맺어 수익률만 따라가는 방식이에요.' WHERE code = '418660' AND seq = 4;
UPDATE etf_name_token SET detail = '이름에 (H)가 없어요. 환율 변동을 막아주는 장치가 없다는 뜻이라, 원달러 환율이 떨어지면 수익이 줄어들 수 있어요.' WHERE code = '418660' AND seq = 5;
UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '435420' AND seq = 1;
UPDATE etf_name_token SET detail = '미국 나스닥 시장의 기술 중심 대형기업 100개를 묶은 지수예요.' WHERE code = '435420' AND seq = 2;
UPDATE etf_name_token SET detail = '국가나 기업이 돈을 빌리면서 발행하는 증서예요. 주식보다 덜 흔들리는 대신 크게 오르기도 어려워요.' WHERE code = '435420' AND seq = 3;
UPDATE etf_name_token SET detail = '주식과 채권을 한 상품에 함께 담는다는 뜻이에요.' WHERE code = '435420' AND seq = 4;
UPDATE etf_name_token SET detail = '주식과 채권을 반반씩 담는다는 뜻이에요. 이름 맨 앞에 ''미국나스닥100''이 있어서 기술주 상품처럼 보이지만, 실제로는 절반이 채권이에요.' WHERE code = '435420' AND seq = 5;
UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '441680' AND seq = 1;
UPDATE etf_name_token SET detail = '미국 나스닥 시장의 기술 중심 대형기업 100개를 묶은 지수예요. 애플, 마이크로소프트, 엔비디아 같은 기업이 포함돼 있어요.' WHERE code = '441680' AND seq = 2;
UPDATE etf_name_token SET detail = '갖고 있는 주식을 정해진 가격에 팔기로 약속(콜옵션 매도)하고 그 대가를 받는 방식이에요. 매달 받는 돈이 생기는 대신, 주가가 크게 올라도 약속한 가격까지만 받을 수 있어요.' WHERE code = '441680' AND seq = 3;
UPDATE etf_name_token SET detail = '실제로 나스닥100 주식을 직접 사는 게 아니라 증권사와 계약을 맺어 수익률만 따라가는 방식이에요.' WHERE code = '441680' AND seq = 4;
UPDATE etf_name_token SET detail = '미래에셋자산운용의 ETF 브랜드예요. 어떤 회사가 이 상품을 만들고 운용하는지 알려주는 부분이에요.' WHERE code = '448290' AND seq = 1;
UPDATE etf_name_token SET detail = '미국에 상장된 대형 회사 500개를 묶은 지수예요. 애플, 마이크로소프트, 엔비디아 같은 기업이 여기에 포함돼 있어요.' WHERE code = '448290' AND seq = 2;
UPDATE etf_name_token SET detail = '미국 주식에 투자하면 보통 달러와 원 환율 변동에 영향을 받아요. 그러나 (H)는 환율 변동을 막아두는 장치가 있다는 뜻이에요. 대신 그 장치를 유지하는 비용이 들어요.' WHERE code = '448290' AND seq = 3;
UPDATE etf_name_token SET detail = '미국 운용사 글로벌엑스의 ETF 브랜드예요. 월분배 상품을 많이 만드는 회사예요.' WHERE code = 'QYLD' AND seq = 1;
UPDATE etf_name_token SET detail = '미국 나스닥 시장의 기술 중심 대형기업 100개를 묶은 지수예요. 애플, 마이크로소프트, 엔비디아 같은 기업이 포함돼 있어요.' WHERE code = 'QYLD' AND seq = 2;
UPDATE etf_name_token SET detail = '갖고 있는 주식을 정해진 가격에 팔기로 약속(콜옵션 매도)하고 그 대가를 받는 방식이에요. 매달 받는 돈이 생기는 대신, 주가가 크게 올라도 약속한 가격까지만 받을 수 있어요.' WHERE code = 'QYLD' AND seq = 3;
UPDATE etf_name_token SET detail = '거래소에 상장되어 주식처럼 사고팔 수 있는 펀드를 말해요.' WHERE code = 'QYLD' AND seq = 4;
UPDATE etf_name_token SET detail = '미국 운용사 프로셰어스의 ETF 브랜드예요. 레버리지·인버스 상품을 주로 만드는 회사예요.' WHERE code = 'TQQQ' AND seq = 1;
UPDATE etf_name_token SET detail = '3배를 뜻하는 표기예요. 이 회사는 2배 상품에 ''Ultra'', 3배 상품에 ''UltraPro''를 붙여요. 이름 어디에도 숫자 3이 없어서 알아채기 어려워요.' WHERE code = 'TQQQ' AND seq = 2;
UPDATE etf_name_token SET detail = '미국 나스닥100 지수를 따라가는 대표 ETF의 종목 코드예요. 여기서는 그 지수를 가리켜요.' WHERE code = 'TQQQ' AND seq = 3;
UPDATE etf_name_token SET detail = '이름에 ''Short''가 없으면 지수와 같은 방향으로 움직인다는 뜻이에요. ''Short''가 붙으면 반대 방향으로 움직여요.' WHERE code = 'TQQQ' AND seq = 4;

ALTER TABLE etf_name_token ALTER COLUMN detail SET NOT NULL;
