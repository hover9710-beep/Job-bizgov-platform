# 배포확정 폴더 인덱스

## 누적 배포 후보 목록 (최신순)

| 날짜 | 폴더 | 핵심 변경 | 배포 상태 |
|---|---|---|---|
| 2026-05-12 (밤) | [2026-05-12_b057_v2_cherrypick](./2026-05-12_b057_v2_cherrypick/) | b057 Phase 2.1f follow-up — jbtp 사이트 url 파라미터 순서 변경 대응 + v1 connector url 정규화 + 누적 137건 갱신 + Render sync (v1 `0032f32`+`06c02fe`, v2 patch export) | 🟡 v2 cherry-pick 대기 (docs 0002 만 직접 apply / 코드 0001 은 029 통째 sync 와 함께 수동 포팅) |
| 2026-05-12 (저녁) | (commit only) | b057 Phase 2.1e Step E + merge_jb notice_order drop fix (v1 `75d5265` / v2 `47ebdf3`) | 🟢 배포 완료 (Render auto-deploy) |
| 2026-05-05 | [2026-05-05_aT-connector](./2026-05-05_aT-connector/) | aT 글로벌 커넥터 추가 (200건, 백로그 024) | 🟡 v1 push 대기 |
| 2026-05-04 | [2026-05-04_deploy-004](./2026-05-04_deploy-004/) | 영구 disk 전환 + db/biz.db 정적 사본 | 🟡 v1 cherry-pick 대기 |
| 2026-05-02 | [2026-05-02_run_security](./2026-05-02_run_security/) | /run 보안 패치 | 🟡 대기 |

## 배포 워크플로우
1. 배포확정 폴더에서 적용할 항목 선택
2. v1 백업 (backup/deploy_YYYYMMDD_HHMMSS/)
3. v1 vs release/ diff 확인
4. v1에 수동 적용
5. 검증 (MANIFEST.md의 검증 절차 따름)
6. 사용자 직접 git commit + push
7. Render 자동 배포 확인
8. MANIFEST.md의 배포 상태 업데이트
9. INDEX.md의 배포 상태 업데이트

## 원칙
- ❌ 모두 배포 절대 금지 (선택적 cherry-pick)
- ✅ 배포 전 항상 백업 (날짜별 별도 보관)
- ✅ git 항상 업데이트 (배포 이력 추적)
