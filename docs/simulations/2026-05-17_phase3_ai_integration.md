# 2026-05-17 시뮬 (통합 갱신) — Phase 3 AI 본문 분석 + 기존 첨부 인프라 재사용

> **분류**: 영향 분석 (코드 변경 X, DB 변경 X) — Phase 3 사전 시뮬 2번째 갱신
> **선행 entry**: [2026-05-17_phase3_attachment.md](2026-05-17_phase3_attachment.md) (1차, gap 식별)
> **시점**: 5/17 → 5/19 사후 정밀 조사
> **누적 entry**: 6번째 (b066 / b033 / Phase 2 / Phase 3 1차 / Phase 3 통합 [본]) + 회고 backfill 보류
> **사용자 통찰**: "이게 AI 의 가장 기본 — 여기서 AI 분석 추천이 들어갈꺼야"
> → Phase 3 = BizGovPlanner AI 의 진짜 시작점 (메타 → 본문)

---

## 🚨 사전 가정 정정 (재정정 + 5/19 22시 9번째)

| 사용자 가설 | 실측 | 정정 |
|---|---|---|
| 기존 첨부 시스템 매일 작동 | jbexport 만 60 .bin / 다른 7 source 첨부 다운로드 X (메타 only) | **jbexport 만 부분 작동, 99.95% 확인필요 = bizinfo 는 미작동** |
| 신규 라이브러리 필요 | `file_text_extract.py` (pypdf + HWPX ZIP+XML) + `attachment_text_pipeline.py` (traversal) 이미 존재 | **PDF + HWPX 추출 인프라 ✓, HWP binary 만 미지원** |
| DB 스키마 신설 | `pdf_path` / `attachments_json` / `attachment_text` / `period_text` 4개 컬럼 이미 존재 | **메타 컬럼 4개 재사용, AI 결과 컬럼 (12~15개) 만 신규** |
| 기존 → DB 통합 자동 | `attachment_text_pipeline.py` 는 `.txt` 저장만 / DB write 없음 | **신규 작업 = DB UPDATE 통합 (간단)** |
| AI 본문 분석 미구현 | `ai_analyzer.py` 존재하나 hardcoded 스텁 (실 호출 X) | **신규 AI 모듈 신설 필수** |
| **9 (5/19 22시)** — bizinfo 첨부 다운로드 신설 (4~6h) 필요 | **사이트 캡처 발견**: bizinfo 는 첨부 파일 X (또는 거의 없음), "첨부서류" 자체가 본문으로 구성. 신청기간 본문에 명확 표시 (예: "신청기간: 2026.01.26 ~ 2026.12.31"). `parse_bizinfo_dates` 이미 신청/사업/공고기간 라벨 지원, `period_text` 컬럼 활용 중 | **Phase 3.0 재정의 = bizinfo 본문 파싱 강화 (1~2h, 첨부 다운로드 불필요)** |

→ **Phase 3 작업량 = 3.5~5일 (이전 5~7일 대비 1.5~2일 감소)**.
→ 인프라 재사용 비율 50%+ (5/19 정정으로 ↑, 단계 분할 유지).
→ 사용자 가설 정정 누계: **9건** (5/17 마라톤 6 + 통합 시뮬 1 + 본 발견 2).

---

## 1. 기존 인프라 정밀 조사 (Step 1, 2 결과)

### 1-A. 디스크 실측 (`data/` 총 ~117 MB)

| 디렉터리 | 파일 수 | 크기 | 비고 |
|---|---|---|---|
| `data/jbexport/files/` | 60 .bin | 15.6 MB | PDF / HWPX / HWP binary 혼합 (확장자 `.bin` 통일) |
| `data/jbexport/` (메타) | 9 .json | 0.1 MB | 일자별 신규 공고 dump |
| `data/history/` | 10 .json | 77.6 MB | 누적 백업 |
| `data/at_global/`, `bizinfo/`, `jbbi/`, `kseafood/`, `kstartup/` | 각 1 .json | <1.1 MB | **메타만 / 첨부 파일 다운로드 X** |
| `data/files/` (top) | 0 | 0 | 미사용 |
| `data/text/` | 0 | 0 | 추출 결과 미생성 (pipeline 실행 X) |

`.bin` 파일 매직바이트 분포 (jbexport 60건):
- `%PDF-1.x` (PDF) — 다수
- `PK\x03\x04` (ZIP / HWPX) — 다수
- `\xd0\xcf\x11\xe0` (OLE compound / HWP binary) — 일부 ⚠️ 미지원

### 1-B. DB 컬럼 실측 (`biz_projects`)

```
pdf_path           TEXT
attachments_json   TEXT
attachment_text    TEXT
period_text        TEXT
```

source 별 채워짐 (4,691 total):

| source | total | pdf_path | atext | ptext | attachments_json |
|---|---|---|---|---|---|
| at_global | 206 | 0 | 0 | 206 | 0 |
| bizinfo | 2,980 | 3 | 0 | 2 | 0 |
| jbbi | 373 | 0 | 0 | 30 | 0 |
| **jbexport** | 72 | 1 | 0 | 29 | **59 (82%)** |
| jbtp | 150 | 0 | 0 | 117 | 0 |
| jbtp_related | 74 | 0 | 0 | 74 | 0 |
| kseafood | 244 | 0 | 0 | 244 | 0 |
| kstartup | 592 | 0 | 0 | 537 | 0 |

핵심 관찰:

- **`attachment_text` 전체 0건** → 추출 pipeline 단 한 번도 DB UPDATE 통합 안됨
- **`attachments_json` jbexport 만 59건** → 메타 수집 7 source 미구현
- **bizinfo 첨부 0건** → 99.95% 확인필요 단일 source 의 첨부 자체 부재 ⭐
- `period_text` 856건 — 메타 추출 (`period_text` 만) 은 부분 작동

### 1-C. 코드 인프라 (이미 존재)

| 모듈 | 역할 | 상태 |
|---|---|---|
| `pipeline/file_text_extract.py` | PDF (pypdf) + HWPX (zip+xml) + HWP (stub, 빈 문자열 반환) | ✓ 작동 (HWP binary 만 미지원) |
| `pipeline/attachment_text_pipeline.py` | `data/**/files` traversal → `data/text/*.txt` | ✓ 작동 / **DB write 없음** |
| `connectors/connector_bizinfo.py` 외 7개 | 사이트별 메타 수집 | ✓ 작동 / **첨부 다운로드 jbexport 만** |
| `ai_analyzer.py` (root) | AI 본문 분석 | ✗ hardcoded 스텁 (실 호출 X) |
| `mailer.py`, `pipeline/send_email.py` | 메일 발송 | ✓ 작동 |
| `pipeline/ai_translate.py`, `ai_summary.py` | 메타 AI (Phase 2 완료) | ✓ 100% coverage |

---

## 2. Phase 3 재정의 — 9 단계 + 보완 6/7/8

### 2-A. 단계 분할 (5/17 임계 — 본 구현 >2일 → 강제)

| Phase | 목표 | 작업량 | 의존 |
|---|---|---|---|
| **3.0** | **bizinfo 본문 파싱 강화** (5/19 9번째 정정) — `parse_bizinfo_dates` 정규식 확장, 신청/사업/공고기간 라벨 우선순위, `period_text` 활용, `infer_status` 재실행 | **1~2h** ⬇ (이전 4~6h) | — |
| 3.1 | `attachment_text_pipeline.py` 에 DB UPDATE 통합 (UPSERT `attachment_text`, `attachment_text_method`) — jbexport 60 file 처리 | 0.5일 | 3.0 |
| 3.2 | AI 본문 기본 분석 (end_date_inferred, eligibility, amount, period, procedure) — GPT-4o-mini batch | 1~1.5일 | 3.1 |
| 3.3 | AI 본문 심층 (deep_summary 300~500자, procedure_steps JSON, required_documents JSON, bonus_criteria) | 2일 | 3.2 |
| 3.4 | 위젯 노출 (첨부 파일명 + deep_summary expand + procedure_steps 시각화) | 0.5~1일 | 3.3 |
| 3.5 | `infer_status(end_date_inferred)` 재분류 | 0.5일 | 3.2 |
| **합계** | | **3.5~5일** ⬇ (이전 5~7일) | |

(선택) 후속 단계:
- 3.6: 나머지 6 source (at_global / jbbi / jbtp / jbtp_related / kseafood / kstartup) 첨부 다운로드 — W22+ (확인필요 0건이라 우선순위 후순위)
- 3.7: HWP binary 지원 (LibreOffice headless 또는 pyhwp) — PoC 0.5일 → 작동 시 정식

### 2-B. 의도된 결과

- 확인필요 2,126 → **300~500** (bizinfo 첨부 80% 보유 가정 + AI end_date 추출 정확도 70% 가정)
- "한국 최초 솔로 + AI" 차별점 = 본문 분석 + 회사 매칭 (Phase 4) 가능
- 응모서 차별점 #8 / #9 의 실 기반 확보

---

## 3. 영향 받는 시스템 영역

| 영역 | 영향 | 비고 |
|---|---|---|
| `connectors/connector_bizinfo.py` | 신규 함수: `_download_attachments(item)` | 사이트 selector 신설 |
| DB 스키마 | 신규 컬럼 12~15개 (아래 3-A) | `_ensure_schema.py` 확장 |
| `pipeline/attachment_text_pipeline.py` | DB UPDATE 통합 | 기존 file traversal 유지 |
| AI 모듈 신설 | `pipeline/ai_body_basic.py`, `pipeline/ai_body_deep.py` | Phase 2 패턴 복제 |
| 운영 sync | 메타만 sync (text 본문 분리), `synced_to_render = 0` reset patch (Phase 2.1 backlog 와 통합) | Render 디스크 1GB 부족 회피 |
| Actions yaml | `daily-crawl.yml` 에 `ai_body_basic` / `ai_body_deep` step | 시간 부족 시 별도 weekly schedule |
| UI | `templates/project_detail.html` 첨부 expand 섹션, 위젯 첨부 표시 | 보라 + ✨ 토글 패턴 유지 |
| 기존 mailer | **영향 X** (별도 흐름, 첨부 메일 발송 작동 유지) | — |

### 3-A. 신규 컬럼 명세 (12~15개)

**첨부 메타 (4개):**
- `attachment_path` TEXT — 로컬 파일 경로
- `attachment_count` INTEGER — 첨부 개수
- `attachment_downloaded_at` TEXT — ISO timestamp
- `attachment_size_kb` INTEGER — 총 크기

**텍스트 추출 (2개, 기존 `attachment_text` 외):**
- `attachment_text_method` TEXT — pypdf / hwpx / hwp_libre / fail
- `attachment_text_chars` INTEGER — 추출 길이

**AI 기본 (5개):**
- `end_date_inferred` TEXT
- `extracted_eligibility` TEXT — 자격 키워드 JSON
- `extracted_amount` TEXT
- `extracted_period` TEXT
- `extracted_procedure` TEXT — 절차 요약

**AI 심층 (3~4개):**
- `deep_summary` TEXT (300~500자)
- `procedure_steps` TEXT — JSON list
- `required_documents` TEXT — JSON list
- `bonus_criteria` TEXT (선택)

→ 총 14~15개 (기존 4개 + 신규 14~15개).

---

## 4. 잠재 사고 5건

| # | 사고 | 확률 | 영향 | 대응 |
|---|---|---|---|---|
| A | bizinfo selector 사이트 변경 시 깨짐 | 중 | Phase 3.0 실패 | PoC 1일 + 정규식 fallback + fail 로그 |
| B | HWP binary 미지원 → 추출 실패 | 높음 | 일부 row text 부재 | `attachment_text_method = "hwp_unsupported"` 명시, AI 가 fallback 처리 |
| C | AI hallucination (end_date 부정확) | 중 | status 재분류 오류 | prompt 가드 + 정규식 후검증 + `end_date_confidence` 컬럼 |
| D | Render 디스크 1GB 부족 (첨부 누적 시) | 낮음 | sync 실패 | 첨부 파일 미동기 (PC 만 보관), text 컬럼만 sync |
| E | 기존 jbexport 첨부 시스템 회귀 | 낮음 | 기존 60 파일 손실 | 읽기 전용 통합 + 신규 파일은 별도 경로 (`data/bizinfo/files/`) |

---

## 5. 의존성

- `pypdf` (이미 import) ✓
- `zipfile`, `xml.etree.ElementTree` (stdlib) ✓
- `openai` (Phase 2 사용 중) ✓
- (신규) HWP binary: `pyhwp` 또는 LibreOffice headless — PoC 결정
- (선택) `requests` (bizinfo 다운로드, 이미 사용 중) ✓

---

## 6. 4 환경 영향

| 환경 | 다운로드 | 추출 | AI | sync |
|---|---|---|---|---|
| v1 PC | ✓ 메인 | ✓ 메인 | ✓ 메인 | 메타 + text sync |
| v1 Render | ✗ (디스크 부족) | ✗ | ✗ | 메타 + text 수신 |
| Actions | △ (시간 부족 가능) | △ | △ | weekly schedule 권장 |
| v2 dev | 독립 | 독립 | 독립 | — |

---

## 7. ROLLBACK 전략

- 신규 컬럼 ALTER 후 NULL 허용 (기존 row 영향 X)
- 단계별 ROLLBACK (3.0 → 3.5 각 독립)
- 기존 jbexport 60 파일 read-only 보호
- AI 결과는 cache 테이블 분리 (`ai_body_cache` 신규) → 본 row 영향 X
- 실패 시 `attachment_text_method = "fail"` flag 로 격리

---

## 8. AI 작업 명세 + 시간 + 비용

### 8-A. AI 호출 추정

| 단계 | 모델 | 입력 | 처리 row | 비용 |
|---|---|---|---|---|
| 3.2 기본 | GPT-4o-mini | 3,000 token (본문 chunk) | 2,500 (bizinfo + 기존 jbexport 59) | ~$5 |
| 3.3 심층 | GPT-4o-mini | 5,000 token | 2,500 | ~$13 |
| 일일 신규 (cron) | GPT-4o-mini | 5,000 token × ~30 신규 | 30/day | ~$0.04/day |
| 연 누적 | | | | **~$14/year** |

→ Phase 2 비용 ($2.94) 대비 약 5배, 솔로 운영 한도 내 (월 ~$1.2).

### 8-B. 시간 분할

| 작업 | 시간 |
|---|---|
| Phase 3.0 PoC (bizinfo 1 site selector) | 4~6h |
| 3.1 DB UPDATE 통합 | 4h |
| 3.2 AI 기본 batch + chunked | 1~1.5일 |
| 3.3 AI 심층 + JSON parsing | 2일 |
| 3.4 UI 위젯 + expand | 0.5~1일 |
| 3.5 status 재분류 + 검증 | 0.5일 |
| 시뮬 회고 + INDEX 갱신 | 0.5일 |
| **합계** | **5~7일** |

---

## 9. 응모서 가치 강화 (차별점 7/8/9 통합)

### 9-A. 차별점 7 — 다중 업종 솔로 사업가

> 솔로 개발자 1인이 여러 업종 도메인 (창업지원 / 농수산식품 수출 / 바이오 / 기술혁신) 의 공고를 통합 운영. 도메인 적응력 = 신호.

(주: 사용자 추가 elaboration 필요 — 본 시뮬에서는 placeholder.)

### 9-B. 차별점 8 — Phase 3 = 본문 AI 분석 시작점

> 지금까지의 BizGovPlanner = 메타 작업 (제목, 한줄요약, 통역).
> Phase 3 부터 = **본문 AI 분석**.
>
> - 자격 자동 매칭 (회사 정보 vs 공고 자격)
> - 신청서 작성 도우미 (필수 서류 목록 자동 추출)
> - 합격 가능성 분석 (가산점 / bonus_criteria 매칭)
> - end_date / 절차 자동 추출 (status 재분류 정확도 ↑)
>
> → "메타 AI 100% → 본문 AI" = BizGovPlanner AI 의 진짜 시작점.

### 9-C. 차별점 9 — Phase 4 = 회사 매칭 추천

> Phase 3 의 본문 텍스트 + Phase 4 의 `target_company`:
>
> - 본문 키워드 분석 (업종 / 매출 / 인원 / 지역)
> - target_company vs 공고 자격 매칭
> - 진짜 맞춤 추천 (현재 위젯 임시 안내 → 실 결과 교체)
> - 사용자 시간 절약 (관련 공고 자동 제시)
>
> → "단순 추천" 이 아닌 **본문 기반 맞춤 추천**.

→ 한국 최초 솔로 + AI 의 **'메타 → 본문 → 매칭 → 추천' 통합 시스템**.

---

## 보완 6 — 사용자 가설 vs 실측

| 가설 | 실측 | 정정 |
|---|---|---|
| 첨부 파일 이미 v1 존재 | jbexport 만 60 .bin / 다른 7 source 0 | 부분 사실 |
| 매일 다운로드 + 메일 발송 | jbexport 첨부만 부분 / 메일 발송 자체는 작동 | 부분 사실 |
| 활용 가능 (신규 구축 X) | 인프라 30~40% 재사용 / 핵심 (bizinfo connector + AI) 신규 | **추가 신설 필요** |
| 가장 큰 활용 = mailer | 영향 X / mailer 별도 흐름 | 무관 |

→ 6번째 사용자 가설 정정 (이전 5건 + 본 1건 = **6건**).

---

## 보완 7 — 인프라 재사용 비율

| 영역 | 재사용 | 신규 |
|---|---|---|
| 다운로드 인프라 (jbexport 만) | 100% | bizinfo 신규 |
| 파일 저장 (`data/<src>/files/`) | 100% | 7 source 디렉터리 사용 |
| 메타데이터 (DB 컬럼 4개) | 100% | — |
| 텍스트 추출 (pypdf + HWPX) | 100% | HWP binary 만 신규 |
| `attachment_text_pipeline.py` traversal | 80% | DB write 통합 |
| AI 본문 분석 | 0% | **전체 신규** |
| 위젯 노출 | 0% | **전체 신규** |
| Phase 2 패턴 (batch + chunked + 멱등성) | 60% | 본문 token 큰 만큼 chunk size 조정 |

**재사용 평균: 35%** (5/17 임계 70% 미만 → 단계 분할 강제 적용 ✓)

---

## 보완 8 — 단계 분할 임계점

본 구현 = 5~7일 → **단계 분할 강제** (>2일 임계 초과).

- 6단계 분할 (3.0 ~ 3.5)
- 각 단계 0.5~2일
- 단계별 시뮬 + 본 구현 + 회고
- 단계별 ROLLBACK 독립

5/17 마라톤 학습 사이클 1 차단 체크리스트 (8항목) 통과 여부:

| # | 항목 | 본 Phase 3 |
|---|---|---|
| 1 | DB 실측 우선 | ✓ (Step 1, 2 완료) |
| 2 | 인프라 재사용 ≥70%? | ✗ 35% → 단계 분할로 회피 |
| 3 | batch + chunked 패턴 | ✓ Phase 2 복제 |
| 4 | DRY-RUN + --limit 10 | ✓ 3.0 PoC 단계로 강제 |
| 5 | 단계 분할 (>2일이면 필수) | ✓ 6단계 |
| 6 | 신규 backup | ✓ 단계 진입 시마다 DB backup |
| 7 | 운영 sync 정책 | ✓ 메타 + text sync, 첨부 본체는 PC 만 |
| 8 | 회고 entry backfill 계획 | ✓ 단계 종료 시 즉시 |

→ 8/8 통과 (5/17 패턴 적용).

---

## 진행 시점 + 일정

| 주차 | 작업 |
|---|---|
| W20 (5/18 ~ 5/20) | 응모서 모드 + 시연 (Phase 3 진입 X) |
| W21 (5/21 ~ 5/27) | **Phase 3.0 PoC** (bizinfo 첨부 4~6h) + 3.1 (DB 통합 0.5일) |
| W22 (5/28 ~ 6/3) | Phase 3.2 (AI 기본) + 3.3 (AI 심층 시작) |
| W23 (6/4 ~ 6/10) | Phase 3.3 (AI 심층 완료) + 3.4 + 3.5 |
| W24 (6/11 ~ 6/17) | Phase 4.1 (target_company 활용) |
| W25 (6/18 ~ 6/24) | Phase 4.2 (매칭 알고리즘) + 4.3 (추천 UI) |
| W26 (6/25 ~ 7/2) | 응모서 본 작성 |
| 7/3 | **본 응모 (JBTP)** |

---

## 다음 사이클 진입 조건

Phase 3.0 진입 전 결정 필요:

- [ ] **HWP binary 지원 결정** — `pyhwp` (Python only) vs LibreOffice headless (시스템 의존) PoC 결과
- [ ] **bizinfo 사이트 selector 안정성** — 1회 PoC 후 정규식 fallback 준비도
- [ ] **Render 디스크 정책 최종 확정** — text 만 sync, 첨부 파일 PC only
- [ ] **AI 비용 예산** — 월 ~$1.2 한도 확정
- [ ] **응모서 모드 종료 시점** — 5/20 시연 후 즉시 vs 5/22 회복 후

---

## 관련 파일

- 1차 sim: `docs/simulations/2026-05-17_phase3_attachment.md`
- Phase 2 sim: `docs/simulations/2026-05-17_phase2_ai_summary.md`
- 표준 template: `docs/templates/feature_impact_simulation.md`
- 응모서 카피: `docs/proposal/2026-07-03_jbtp_intro_copy.md`
- 첨부 추출 모듈: `pipeline/file_text_extract.py`, `pipeline/attachment_text_pipeline.py`
- 8 connector: `connectors/connector_*.py`
- AI 스텁 (교체 대상): `ai_analyzer.py`
