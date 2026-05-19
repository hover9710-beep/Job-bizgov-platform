# 메일 시스템 정확 흐름 검증 (5/18 작업)

**작성**: 2026-05-17 EOD 정정
**상태**: 백로그 (5/18 작업 묶음 30분 추가)

---

## 배경

5/17 EOD 사용자 메모 확인 결과:

- nate 메일 (`hover1234@nate.com`) = 사용자 일반 사용자로서 수신 (확인됨)
  - 웹에서 회사 정보 직접 등록
  - 매일 09:13 KST 추천 메일 수신
- gmail (`hover9710@gmail.com`) = 크롤러 fail 알림 (사용자 기억, 미검증)
  - 운영 모니터링 목적

이전 해석 오류 정정:
- ❌ hover9710@gmail.com 으로 발송 (아님)
- ❌ 사용자가 정부24/aT/모두의 창업 정책 직접 수신 (아님)

---

## 확인 사항

### 1. Google Apps Script 코드 (`sendDailyBizGovEmails`)

- 위치: Google Apps Script 콘솔
- 작동: 09:13 KST 매일 자동 트리거
- 수신: 등록된 모든 회사 (nate 등 다양한 메일 도메인)
- 확인 포인트:
  - 발송 대상 쿼리 로직
  - 추천 매칭 알고리즘 (Phase 3-4 통합 시 갱신)
  - ADMIN_EMAIL 변수 (관리자 알림 송신지 후보)

### 2. `hover9710@gmail.com` 의 정확한 역할

- 가설: 크롤러 fail 시 알림 수신
- 확인 방법:
  - (a) Google Apps Script 코드의 ADMIN_EMAIL 변수
  - (b) Actions yaml 의 notify-on-failure 설정
  - (c) `crawler.py` / `pipeline/` 의 except 절 메일 발송 로직

### 3. 메일 발송 흐름 정리

| 구분 | 수신자 | 발송 트리거 | 발송 시스템 |
|---|---|---|---|
| 일반 사용자 | nate 등 등록자 전체 | 09:13 KST daily | Google Apps Script |
| 관리자 알림 | gmail (단일) | 크롤러 fail | 미확인 (a/b/c 중) |

---

## 작업 시간

- 5/18 작업 묶음에 30분 추가
- 새 5/18 합계: 약 3~3.5시간 (기존 2.5~3h + 본 검증 30분)

---

## 응모서 활용

확인 결과를 응모서 6번째 차별점 카피에 반영.
- 정확한 표현 = 평가위원 신뢰도 ↑
- "운영자 = 사용자 = 검증자" 의 구체적 증거 (Apps Script 코드 + Actions yaml)

---

## 관련

- 응모서 카피: `docs/proposal/2026-07-03_jbtp_intro_copy.md` (6번째 차별점)
- 데일리 일지: `docs/daily/2026-05-17_bizgov_marathon.md` (사후 발견 5)
- 다층 노출 전략: `docs/backlog/data_source_trust_display.md`
