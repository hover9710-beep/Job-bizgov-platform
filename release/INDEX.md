# 배포확정 폴더 인덱스

## 누적 배포 후보 목록 (최신순)

| 날짜 | 폴더 | 핵심 변경 | 배포 상태 |
|---|---|---|---|
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
