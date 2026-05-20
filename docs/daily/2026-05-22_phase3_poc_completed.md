# 2026-05-22 — Phase 3.0 PoC 완료 (정량 결과 영구 저장)

> **한 줄 요약**: Phase 3.0 PoC end-to-end 검증 성공 — 확인필요 −856 (−37%), 파싱 정확성 100%, 13번째 가설 정정(enrich 비영구성) 발견
> **참고**: PoC 실행·검증 실제 수행은 5/20 밤. 본 entry는 정량 결과 영구 저장본.

---

## 1. 5/20 — 박람회 마지막 날 + 시연 + 집 작업

- 오전: 박람회장(코리아 씨푸드 쇼 D07) + Phase 3.0 PoC Step 3 본 실행 (부분 성공 35.8%, 박람회장 네트워크 823건 실패)
- 시연 진행
- 밤: 집(안정 네트워크)에서 Step 3 재실행 + Step 4 merge

---

## 2. PoC 정량 결과

| 항목 | 값 |
|---|---|
| 재실행 fetch | 1,474 / 1,474 (네트워크 실패 0건) |
| **DB bizinfo end_date** | 738 → **1,500** (**+762**) |
| **DB bizinfo 확인 필요** | 2,302 → **1,446** (**−856, −37%**) |
| **파싱 정확성** | **100%** (fetch 1,474건 전수 period 필드 정상 추출) |
| 무마감 공고 | 711건 = **48.1%** ("예산소진/선착순/상시/세부사업별 상이" — 정당 추출, 마감일 실제 부재) |
| `bizinfo_all.json` end_date 비율 | 재실행 후 767/1,478 = 51.9% |

- bizinfo status 분포(Step 4 후): 접수중 856 / 마감 738 / 확인필요 1,446
- 검증 파이프라인: `enrich-detail` → `merge_jb.py` → `update_db.py` → DB (입력 4,600건, upsert 실패 0)

---

## 3. 13번째 가설 정정 — enrich 비영구성

- 가설(5/20 오전): "`--enrich-detail` 실행만 = Phase 3.0 완성"
- 실측(5/20 밤): enrich 결과는 **비영구** — 야간 크롤(20:37)이 `bizinfo_all.json` 덮어쓰고, `update_db` UPDATE가 보존 가드 없이 DB `end_date`를 빈값으로 덮어씀
- 결과: **Phase 3 본 구현 = "영구화"가 핵심** (enrich 실행이 아님)
- 5/20 오전 enrich 513건은 같은 날 20:40 야간 크롤로 소멸 → 재실행으로 재생성

→ 누적 가설 정정 13건. 상세: `docs/simulations/2026-05-20_phase3_poc_completed.md`

---

## 4. 백로그 (다음 사이클)

| # | 백로그 | 시간 | 우선순위 |
|---|---|---|---|
| ① | `enrich_persistence.md` — enrich 결과 영구화 | 2~4h | 높음 |
| ② | `no_deadline_classification.md` — 무마감 ~700건 status 재분류 | 30분~1h | 중 |

---

## 5. 안전 자산

- DB 롤백 지점: `db/biz.backup.20260520_234520_pre_step4_merge.db`
- JSON 백업: `bizinfo_all.backup_20260520_092537_pre_enrich.json`, `bizinfo_all.backup_20260520_232809_pre_rerun.json`
- ⚠️ Step 4 DB 반영분은 5/21 20:37 야간 파이프라인이 wipe 예정 (영구화 전까지) — 정량 결과 자체는 본 entry로 영구 저장됨

---

## 관련 파일

- PoC 회고: `docs/simulations/2026-05-20_phase3_poc_completed.md`
- Step 1+2: `docs/daily/2026-05-20_phase3_poc_step1_2.md`
- 백로그: `docs/backlog/enrich_persistence.md`, `docs/backlog/no_deadline_classification.md`
