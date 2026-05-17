# 2026-05-17 시뮬 — Phase 3 (첨부 추출 + end_date 자동 추출)

> **분류**: 영향 분석 (코드 변경 X, DB 변경 X)
> **대상**: 첨부 다운로드 / PDF·HWP 텍스트 추출 / AI end_date 추출 / `infer_status` 재분류
> **시점**: 5/17 EOD (Phase 2 완료 직후)
> **누적 entry**: 4 번째 (선행 b066 / b033 / Phase 2)
> **결정 받기 전 진입 금지**

---

## 🚨 사전 가정 정정 (가장 중요)

| 사용자 가설 | 실측 | 정정 |
|---|---|---|
| "확인 필요" 47% → Phase 3 가 큰 폭 감소 | **확인 필요 2,126 중 첨부 보유 = 0건** | Phase 3 즉시 효과 **0%** |
| 7 source 첨부 부분 작동 | jbexport 만 attachments_json 59건 (82%), 나머지 7 source = **0건** | jbexport 만 부분 작동, 다른 7 source 는 **수집 자체 X** |
| 단순 "추출" 작업 | 실측: 추출 이전에 7 source connector 의 attachments_json 수집부터 신설 필요 | 진짜 1단계 = connector 확장 |

→ **Phase 3 의 실 작업량은 사용자 추정 (5~7일) 보다 큼**. connector 확장 7개 (사이트별 selector) 가 가장 큰 비용.

---

## 1. 작업 정의 (재정의)

### 1-A. 단계 분할 (재정의)

| Phase | 목표 | 작업량 | 의존 |
|---|---|---|---|
| **Phase 3.0** | bizinfo + 6 source connector 의 `attachments_json` 수집 추가 | **2-3일** (사이트별 selector) | — |
| Phase 3.1 | 다운로드 인프라 (`data/files/<source>/`) + 멱등성 | 1일 | 3.0 |
| Phase 3.2 | 텍스트 추출 (`pypdf` + HWP 라이브러리 추가) | 1-2일 | 3.1 |
| Phase 3.3 | AI end_date 추출 (`batch_generate_end_date`) | 1일 | 3.2 |
| Phase 3.4 | `attachment_text` 컬럼 DB UPDATE + status 재분류 | 0.5일 | 3.3 |
| Phase 3.5 | 위젯에 첨부 파일명 노출 (AI 모드만) | 0.5일 | 3.0 |
| **합계** | | **6-8일** | |

### 1-B. 의도된 결과

- "확인 필요" 2,126 → 추정 (Phase 3.0 후 첨부 수집 시 80%+ 보유 가정 시) **500~800 까지 감소**
- 사용자 비전 "이런 회사에 유리" (Phase 4) 의 전제 (attachment_text 보유)
- 7/3 응모서 "Phase 3 통합 완료" 핵심 메시지

---

## 2. 현재 상태 정밀 분석 (실측, 5/17 EOD)

### 2-A. 첨부 컬럼 분포 by source

| source | total | `attachments_json` | `pdf_path` | `attachment_text` |
|---:|---:|---:|---:|---:|
| bizinfo | 2,862 | **0** | 3 | **0** |
| kstartup | 537 | **0** | 0 | **0** |
| jbbi | 373 | **0** | 0 | **0** |
| kseafood | 244 | **0** | 0 | **0** |
| at_global | 206 | **0** | 0 | **0** |
| jbtp | 142 | **0** | 0 | **0** |
| jbtp_related | 74 | **0** | 0 | **0** |
| **jbexport** | 72 | **59 (82%)** | 1 | **0** |

→ **jbexport 만 attachments_json 수집, 7 source 는 모두 0**.
→ **attachment_text 전체 0건** (텍스트 추출 미실행).

### 2-B. "확인 필요" 첨부 보유 — Phase 3 효과 추정

| 항목 | 값 |
|---|---|
| 확인 필요 total | 2,126 |
| 첨부 보유 (Phase 3 해소 가능) | **0 (0%)** |
| 첨부 없음 (Phase 3.0 이후만 해소 가능) | 2,126 (100%) |

### 2-C. 다운로드된 파일 (jbexport 만)

- `data/jbexport/files/`: 55 파일, **15.3 MB**
- `data/files/`: 없음
- 파일 형식: `.bin` (UUID 이름 변환, 원본 PDF/HWP/HWPX)

### 2-D. 라이브러리 (requirements.txt)

| 라이브러리 | 설치 여부 | 비고 |
|---|---|---|
| `pypdf` 6.10.2 | ✅ | PDF 추출 OK |
| `pdfplumber` | ❌ | 한글 표 추출용 (선택) |
| `olefile` | ❌ | HWP 핵심 |
| `pyhwp` / `hwp5` | ❌ | HWP 5.x 추출 |
| `python-docx` | ❌ | DOCX (선택) |

### 2-E. 기존 모듈 (사용 X 상태)

- `pipeline/file_text_extract.py` — extract_text() 함수
- `pipeline/attachment_text_pipeline.py` — 파일 순회 + 텍스트 .txt 저장 (DB X)
- `run_all.py:384` 4e 단계 (non-fatal) — 호출하지만 결과 무용 (DB attachment_text 0건)

---

## 3. 영향 받는 시스템 영역 (10건)

### A. DB 스키마 (신규 컬럼 후보)
| 컬럼 | 타입 | 용도 |
|---|---|---|
| `attachment_text` (기존) | TEXT | 추출 본문 (현재 0건) |
| `attachment_text_at` (신규) | TEXT | 생성 시간 |
| `end_date_inferred` (신규) | TEXT | AI 추출 마감일 (`YYYY-MM-DD`) |
| `end_date_source` (신규) | TEXT | "site" / "attachment" / "ai" / "manual" |

→ `_ensure_schema.py` 의 COLUMNS 에 3 컬럼 추가 (4 환경 자동 ALTER).

### B. crawler 확장 (가장 큰 비용)
- bizinfo, kstartup, jbbi, kseafood, at_global, jbtp, jbtp_related = **7 source**
- 각 사이트의 상세 페이지 selector 분석 필요 (사이트별 마크업 다름)
- 예상 작업: **사이트당 4-6시간 = 총 2-3일**

### C. 다운로드 인프라
- 저장 경로: `data/files/<source>/<filename>.bin` 또는 hash 이름
- 디스크 용량 (Render 무료 1GB):
  - 추정 평균 1MB/파일 × 7 source × 평균 200 첨부 = **약 1.4 GB** 🚨
  - 운영 Render 디스크 한도 초과 위험
  - 대응: 운영은 attachment_text 만 저장 (.bin 파일 미동기) — sync 정책
- 중복 다운로드 방지: file URL hash + size 체크

### D. 텍스트 추출
- PDF: pypdf 6.10.2 (✅ 설치)
- HWP/HWPX: `olefile` + `pyhwp` 추가 필요. **한국어 정확도 낮음** (한글 깨짐 위험)
  - 대안: LibreOffice headless 호출 (Render 환경 변경 필요)
- DOCX: `python-docx` (선택)

### E. AI end_date 추출
- 모델: GPT-4o-mini
- prompt: attachment_text → "마감일 YYYY-MM-DD" 또는 NULL
- 가드: 정규식 검증 (날짜 형식), hallucination 차단
- 비용 추정: 평균 5,000 input tokens × 2,000 행 × $0.150/1M = **~$1.50 (1회)**

### F. `infer_status` 재실행
- 신규 end_date 적용 → 위젯 카운트 재집계
- "확인 필요" 2,126 → (Phase 3.0 후 첨부 수집 + AI 추출 정확도 70% 가정) → **약 600~800 까지 감소 추정**
- 단 이건 가정 기반 (실측 X) — Phase 3.0 작업 후 정확한 효과 측정

### G. 위젯 UI
- 첨부 파일명 표시 위치: `.ai-section` 안 (AI 요약 모드만)
- 첨부 클릭 시: 다운로드 link 또는 새 탭
- 보안: file URL 직접 노출 (origin server 측 인증 없음 가정)

### H. 운영 sync
- 신규 컬럼 3개 (sync_to_render `SYNC_FIELDS` + appy.py `SYNC_UPDATE_WHITELIST` 추가)
- `attachment_text` 는 큰 데이터 (평균 5KB × 2,000 행 = 10MB) — sync payload 크기 ↑
- batch_size 줄여야 할 수도 (현재 500 → 100)

### I. 비용 (전체)
| 항목 | 1회 | 월 (일일 50건) |
|---|---|---|
| 다운로드 | 0 (대역폭) | 0 |
| 텍스트 추출 | 0 (로컬) | 0 |
| AI end_date 추출 | $1.50 (2,000 행) | $0.04 |
| 운영 Render 디스크 | $0 (1GB 한도 안) | $0 |
| **합계** | **$1.50** | **$0.04** |

### J. 응모서 가치 (7/3)
- "확인 필요" 30~50% 해소 = 정확성 향상
- 사용자 비전 Phase 3 완료
- Phase 4 (target_company) 의 전제 충족

---

## 4. 잠재 사고 시나리오 (5건)

| # | 시나리오 | 위험 | 대응 (5/17 b066/b033 패턴 활용) |
|---|---|---|---|
| A | 7 source connector 의 selector 다양성 — 일부 사이트 변경 시 깨짐 | 🔴 높음 | 사이트별 connector 별도 PR + 회귀 검사 (b033 canonical_url 패턴) |
| B | HWP 한글 깨짐 → 텍스트 추출 손실 30%+ | 🔴 매우 높음 | PoC 우선 (1 일) — 정확도 측정 후 LibreOffice headless 결정 |
| C | AI end_date hallucination (잘못된 날짜) | 🟡 중간 | 정규식 검증 + 본문에 없는 날짜는 NULL 강제 (b066 prompt 가드 패턴) |
| D | Render 디스크 1GB 한도 초과 | 🔴 높음 | 운영은 .bin 미동기, attachment_text 만 sync (b069 v1 master 정책) |
| E | 5/13 b035 회고 — 위젯 정렬 변경 X | 🟢 0 | Phase 3 는 status 컬럼만 영향, ORDER BY 절 미터치 |

---

## 5. 의존성

- `pypdf` 6.10.2 ✅ (PDF)
- `olefile`, `pyhwp` ❌ (HWP — 추가 필요)
- `pipeline/ai_translate.py` `batch_generate_friendly` 패턴 → `batch_generate_end_date` 신설 가능
- `pipeline/ai_summary_cache.py` batch + chunked commit 패턴 (재사용)
- `_ensure_schema.py` 컬럼 추가 (3 컬럼)
- `sync_to_render.py` SYNC_FIELDS 확장 + appy.py SYNC_UPDATE_WHITELIST

---

## 6. 4 환경 영향

| 환경 | Phase 3 영향 |
|---|---|
| v1 PC | 첨부 다운로드 + AI 추출 + DB UPDATE (디스크 부담) |
| v1 Render 운영 | `attachment_text` + `end_date_inferred` sync. 첨부 .bin 미동기 |
| Actions runner | 매 cron 새로 다운로드 (캐시 X). 한 번에 200 첨부 시 timeout 위험 |
| v2 dev | 별개 (영향 0) |

---

## 7. ROLLBACK plan

- 신규 컬럼 ALTER 후 NULL 허용 → 데이터 손실 0
- `attachment_text` 만 reset: `UPDATE biz_projects SET attachment_text = NULL`
- `end_date_inferred` 만 reset: 동일 패턴
- 단계별 rollback (다운로드 → 추출 → AI 각각 독립)
- 백업: `db/biz.db.backup_phase3_pre_*` (1회)
- 복구 시간: < 5분

---

## 8. 5/20 시연 영향

| 시점 | Phase 3 상태 |
|---|---|
| 5/17 EOD (지금) | 분석만, 본 구현 X |
| 5/18 ~ 5/20 | 시연 안정 모드 — 본 구현 진입 X |
| **5/21 W21** | **Phase 3.0 진입 (사용자 결정 후)** |
| 6/1 ~ 6/15 | Phase 3.0~3.5 완료 |
| 6/16 ~ 7/3 | Phase 4 진입 + 응모서 |

→ 시연 후 W21 진입 권장.

---

## 9. 5 보완

### 보완 1: 응모서 vs 시연 분리

- 5/20 시연: 현재 시스템 (b066~b070 까지). Phase 3 = "향후 비전" 노출
- 7/3 응모서: Phase 3.x 완료된 상태로 핵심 차별점 메시지

### 보완 2: 단계별 진입 권장 (재정의)

| Step | 작업 | 시간 |
|---|---|---|
| Phase 3.0 | 7 source connector 의 attachments_json 수집 (사이트별 selector) | **2-3일** |
| Phase 3.1 | 다운로드 인프라 (멱등 + 디스크 관리) | 1일 |
| Phase 3.2 | 텍스트 추출 (pypdf + olefile + pyhwp PoC) | 1-2일 |
| Phase 3.3 | AI end_date 추출 (batch + chunked commit) | 1일 |
| Phase 3.4 | DB UPDATE + status 재분류 | 0.5일 |
| Phase 3.5 | 위젯에 첨부 노출 (.ai-section 통합) | 0.5일 |

→ 각 단계 독립 시뮬 entry + 본 구현 + 회고

### 보완 3: Phase 4 와의 시너지

Phase 3 의 `attachment_text` 가 Phase 4 의 핵심 input:
- prompt: title + ai_summary + **attachment_text** → "이런 회사에 유리"
- attachment_text 없으면 Phase 4 정확도 크게 낮음 (현재 description 도 거의 empty)
→ **Phase 3.0~3.2 가 Phase 4 의 전제 조건**.

### 보완 4: 5/17 b066/b033/b069 패턴 재사용 비율

| 5/17 패턴 | Phase 3 재사용 가능 |
|---|---|
| `_ensure_schema.py` 컬럼 추가 | ✅ (3 컬럼) |
| `batch_generate_*` GPT 호출 | ✅ (end_date 추출) |
| `chunked commit` (50건) | ✅ (DB UPDATE) |
| `--widget-targets` 인자 패턴 | ✅ (재사용 가능) |
| sync `SYNC_FIELDS` + `SYNC_UPDATE_WHITELIST` 양측 | ✅ (3 컬럼) |
| Actions yaml step 추가 | ✅ (`ai-end-date` step) |
| `db/biz.db.backup_phase3_pre_*` | ✅ |
| `WHERE col IS NULL` 멱등 | ✅ |

→ **재사용 비율 ~80%**. 신규 인프라는 connector 확장 + HWP 라이브러리 + 다운로드 인프라만.

### 보완 5: "확인 필요" 해소 정확 추정 (현재 = 0%)

- **현재 시점**: 첨부 보유 0건 → Phase 3 효과 **0%**
- **Phase 3.0 완료 후** (7 source 첨부 수집 가정):
  - bizinfo 2,862 행 중 첨부 보유 추정 80% = 2,290 행 (Phase 3.1~3.2 후 텍스트 추출 가능)
  - 그 중 AI end_date 추출 정확도 70% = **약 1,600 행 해소 가능**
  - 확인 필요 2,126 → 약 **500~700 까지 감소 (75% 해소)**
- **단 추정** — Phase 3.0 작업 후 정확 측정

---

## 🎯 종합 권고

### 진행 시점 권고: **W22~W23 (시연 + 응모 안정화 후)**

이유:
1. 5/20 시연 임박 — 안정 모드 우선
2. Phase 3 = 6-8일 작업 — 한 사이클 안에 X
3. W21 = 시연 회고 + 응모서 초안
4. W22~W23 = Phase 3.0~3.5 본 구현

### 핵심 리스크 3개

1. **HWP 한글 처리 정확도** — PoC 1 일 우선 (LibreOffice headless 가능성 검토)
2. **7 source connector 의 selector 다양성** — 사이트별 별도 PR + 회귀
3. **Render 디스크 1GB 한도** — 운영은 attachment_text 만, .bin 미동기

### Phase 3.0 PoC 우선 (가장 가치 큰 단일 작업)

W21 진입 가능한 단일 PoC:
1. **bizinfo 의 attachments_json 수집만** — bizinfo 가 가장 많은 행 (2,862 = 63%)
2. 1 사이트만 selector 분석 = 4-6시간
3. 결과: bizinfo 행의 첨부 보유 0 → 80%+ 도달
4. Phase 3.1~3.5 의 효과 측정 가능

### 응모서 메시지 (7/3)

> "Phase 3: 첨부 PDF/HWP 자동 분석으로 마감일 자동 추출 — '확인 필요' 47% → 13% 해소.
> Phase 4: 첨부 본문 기반 'AI 가 이런 회사에 유리합니다' 매칭 — 사용자 회사정보 입력 시 정밀 추천."

---

## 🧠 사이클 회고 (사후 backfill — Phase 3 본 구현 후)

| 항목 | 예상 | 실측 | 정확도 |
|---|---|---|---|
| 시간 추정 (6-8일) | TBD | TBD | TBD |
| HWP 정확도 70% 가정 | TBD | TBD | TBD |
| "확인 필요" 해소 75% 가정 | TBD | TBD | TBD |
| 비용 추정 ($1.50) | TBD | TBD | TBD |
| 7 source connector 사이트별 selector 작업 | 7 site × 4~6h | **bizinfo 1개로 99.87% 커버** | **예상 뒤집힘 — 작업량 50%+ 감소** |

---

## 🔴 사후 결정적 발견 (5/17 EOD 추가 — 사용자 사이트 캡처)

> **트리거**: 사용자가 위젯 "확인 필요" 카드의 실 분포를 사이트에서 직접 확인.

### 발견

| 측면 | 시뮬 본문 가정 (5/17 14:00) | 사이트 캡처 실측 (5/17 EOD) |
|---|---|---|
| "확인 필요" 의 source 분포 | 7 source 분산 가정 → connector 7개 확장 필요 | **99.87% (≈2,123/2,126) = bizinfo(기업마당) 단일** |
| Phase 3.0 작업 단위 | 7 site selector 분석 (2-3일) | **bizinfo 1개 selector 분석 (4~6h)** |
| Phase 3 합계 작업량 | 6-8일 | **3-4일 (50%+ 감소)** |
| Phase 4 의존 (attachment_text) | 7 source 의 첨부 텍스트 | **bizinfo 단일 텍스트로 거의 동일 효과** |

### 함의 재계산

- Phase 3.0 PoC = bizinfo 단일 selector 분석. **다른 6 source 는 후순위 또는 영구 보류 가능**.
- "확인 필요" 해소 추정 75% → **bizinfo 첨부 보유율 80% × AI end_date 정확도 70% = 약 56% 해소** (절대 비율은 시뮬 본문 추정과 비슷, 단 작업량은 절반 이하).
- 응모서 (7/3) 메시지 단순화: **"기업마당 첨부 PDF/HWP 자동 분석으로 마감일 추출 — 확인 필요 99.87% (bizinfo) 해소 56% 달성"**.

### W21~W23 권고 (재정의)

| 변경 전 (시뮬 본문) | 변경 후 (본 발견 반영) |
|---|---|
| W22~W23 Phase 3.0~3.5 (6-8일) | **W21 bizinfo PoC (4~6h) → W22 Phase 3.1~3.5 (3-4일)** |
| 7 source connector 확장 | bizinfo 단일 우선, 나머지 6 source 는 별도 backlog |
| Phase 4 = 7 source 의존 | **Phase 4 = bizinfo 단일 attachment_text 로 충분** |

### 5/17 마라톤 학습 추가

- 사용자 가설 정정 4건 (b066/b033/Phase 2/Phase 3) **+ 사후 결정적 발견 1건** = 5건째 정정.
- 패턴: **시뮬 본문 작성 시 source 분포 미실측 → 사이트 캡처 / 위젯 실측으로 검증** (사이클 1 차단 체크리스트에 추가 검토).
