# 배포확정: 2026-05-04 deploy-004 영구 disk 전환 + db/biz.db 정적 사본

## 마감 정보
- 마감일: 2026-05-04
- 검증 commit (v2): 25522fec
- 작업자: 김형식
- 검증 결과: v1 운영 Persistence test 통과 (visit_log redeploy 후 보존)

## 변경 요약
v1 운영 Render의 ephemeral filesystem 문제 해결.
redeploy마다 동적 데이터(visit_log, click_log 등)가 reset되던 문제를 영구 disk(/var/data) 도입으로 해소.
db/biz.db 자체는 정적 사본(11,694건 정적 데이터만, 동적 7테이블 비움)으로 정리하여 ensure_db_file() 자동 복사가 깨끗한 상태로 동작하도록 함.

## 영향 파일
- db/biz.db (binary)
  - 16,297,984 bytes → 15,310,848 bytes (VACUUM)
  - md5: c23a5e98... → 0516959bda7e7601a8c3d6ff340eeda0
  - 정적 4테이블 보존: biz_projects 11722 / projects 11290 / recommendations 10 / google_form_import_log 2
  - 동적 7테이블 비움(스키마는 보존): click_log, visit_log, companies, consent_logs, user_request_log, favorite_projects, users
- 코드 변경 없음 (ensure_db_file() 로직은 v1/v2 동일하게 이미 존재)

## v1 적용 시 주의사항

### 🚨 환경변수 대소문자 트랩 (중요)
- DB_PATH 값은 반드시 소문자: `/var/data/biz.db`
- ❌ `/Var/data/biz.db` (대문자 V) 입력 시 Linux case-sensitive로 PermissionError 발생
- 실제 사례: 2026-05-04 14:45 첫 시도에서 이 오타로 deploy failed (status 1)
- Render Disk Mount Path도 소문자 `/var/data` 일치 필수

### v1 db/biz.db 충돌 처리
- v1 현재 db/biz.db: 16.5MB (정적+동적 혼재, projects 11,695건)
- v2 정적 사본: 15.3MB (정적만, projects 11,290건)
- cherry-pick 시 binary 충돌 거의 확실
- 해결: theirs(v2 사본) 채택 → `git checkout --theirs db/biz.db` 또는 cherry-pick 시 `-X theirs`

### v1 push 후 Render redeploy 동작
- redeploy 자동 트리거됨
- 단, `/var/data/biz.db` 이미 존재하므로 ensure_db_file()의 `if not target.exists()` 조건이 false → **자동 복사 SKIP**
- 결과: 영구 disk의 운영 데이터(visit_log/click_log 등) 보존됨
- 코드 폴더 db/biz.db만 정적 사본으로 교체되며, 운영에는 직접 영향 없음

### Phase 3에서 .gitignore 추적 해제 예정
- 본 cherry-pick은 db/biz.db를 git에 그대로 둔 상태에서 적용
- Phase 3에서 v1/v2 양쪽 .gitignore에 db/biz.db 추가 + git rm --cached 진행
- 이후로는 db/biz.db가 git에 추적되지 않음

## 사전 의존성 (v1 운영에 이미 적용 완료)
- Render Persistent Disk 1GB 추가 (Mount: /var/data)
- 환경변수 DB_PATH=/var/data/biz.db 설정
- 위 두 개가 먼저 적용되어 있어야 본 cherry-pick의 의미가 있음

## 검증 절차 (v1 cherry-pick 후 필수)

### 1. cherry-pick 직전 baseline 기록 (Render Shell)
```
ls -la /var/data/biz.db
python -c "
import sqlite3
c=sqlite3.connect('/var/data/biz.db').cursor()
print('visit_log total:', c.execute('SELECT COUNT(*) FROM visit_log').fetchone()[0])
print('max(id):', c.execute('SELECT MAX(id) FROM visit_log').fetchone()[0])
print('biz_projects:', c.execute('SELECT COUNT(*) FROM biz_projects').fetchone()[0])
"
```

### 2. v1 push → Render redeploy 완료 대기
- Render Dashboard에서 Live 표시 확인

### 3. cherry-pick 직후 검증 (같은 Render Shell 명령 다시)
- visit_log total: baseline 이상 (감소하면 reset 발생, 비정상)
- max(id): baseline 이상
- biz_projects: 11695 그대로 (변동 없어야 정상)

### 4. 사이트 정상 응답
- https://job-bizgov-platform.onrender.com 200 응답
- "오늘 방문" 카운트 정상 표시

## 롤백 방법
- v2 PC 보관 백업: `db/biz_full_backup_20260504.db`
  - md5: c23a5e98d675b5e3c01cc5773a9f0e20
  - size: 16,297,984 bytes
  - 복원: `cp db/biz_full_backup_20260504.db db/biz.db`
- v1 git 롤백: `git revert <cherry-pick commit hash>` 또는 `git reset --hard HEAD~1` (push 전이라면)
- Render rollback: Dashboard → Rollback 버튼 (이전 성공 deploy로)

## Disaster Recovery (영구 disk 손실/재생성 시)

### 위험 시나리오
Phase 3에서 db/biz.db가 git에서 추적 해제된 후, /var/data/biz.db가 어떤 이유로 손실되면 ensure_db_file()의 fallback(`target.touch()`)이 동작하여 빈 파일이 생성되고, _init_db()가 빈 schema만 만든다 → 정적 데이터(biz_projects 등) 손실.

### 발생 가능 상황
- Render Persistent Disk 손상/삭제 (드뭄)
- 신규 Render 환경 setup
- 영구 disk mount path 변경

### 복구 절차

**1. 백업본 위치 (PC, 로컬 보관)**
- v2: `db/biz_static_only.db` (15.3MB, md5: `0516959bda7e7601a8c3d6ff340eeda0`, 정적만)
- v2: `db/biz_full_backup_20260504.db` (16.3MB, md5: `c23a5e98...`, 정적+동적 백업)
- v1: `db/biz_v1_pre_deploy004_20260504.db` (16.5MB, md5: `fa19dba8...`, cherry-pick 직전 운영 스냅샷)
- 추가: `biz_backup_20260504.b64` (4,620 bytes, 핵심 6테이블 base64 — 사용자 PC 메모장)

**2. 큰 파일 복원 (15MB+, GitHub release/gist 활용)**
PC → 임시 private GitHub release/gist 업로드 → Render Shell에서 wget/curl로 다운로드 → 사용 후 임시 업로드 삭제.

```
# Render Shell 예시
wget -O /var/data/biz.db https://github.com/.../biz_static_only.db
python -c "
import sqlite3
c = sqlite3.connect('/var/data/biz.db').cursor()
print('biz_projects:', c.execute('SELECT COUNT(*) FROM biz_projects').fetchone()[0])
print('projects    :', c.execute('SELECT COUNT(*) FROM projects').fetchone()[0])
"
# 기대: biz_projects 11722, projects 11290 (v2 정적 사본 기준)
```

**3. 작은 데이터셋 복원 (base64 paste)**
biz_backup_20260504.b64 (4,620 bytes) 같은 핵심 6테이블만 복원 시:
```
# Render Shell
echo '<base64 내용>' | base64 -d > /tmp/restore.db
sqlite3 /var/data/biz.db "ATTACH '/tmp/restore.db' AS r; INSERT OR REPLACE INTO ... SELECT * FROM r....; DETACH r;"
```

**4. 검증**
- `sqlite3 /var/data/biz.db "SELECT COUNT(*) FROM biz_projects"` → 정적 데이터 row 수 확인
- 사이트 정상 응답
- /opt/render/project/src/db/ 폴더에는 biz.db 없음 (정상, 추적 해제됨)

**5. 다음 redeploy**
- /var/data/biz.db 존재 → ensure_db_file()의 자동 복사 SKIP
- 운영 그대로 유지

### 예방 조치
- PC 백업본을 OneDrive 외 별도 매체(USB/외장)에 추가 보관 권장
- 정기적으로 PC 백업 ↔ /var/data/biz.db md5 비교 (예: 월 1회)
- 신규 환경 setup 시 본 절차를 사전 실행 (빈 schema 시작 회피)

## 알려진 이슈 / 메모
- v1과 v2의 db/biz.db는 운영 환경 차이로 row 수가 다름 (v1 11695 vs v2 11722/11290). cherry-pick은 v2 사본으로 통일.
- ensure_db_file() 동작이 사실상 마이그레이션을 담당. 별도 마이그레이션 스크립트 불필요.
- v1과 v2 git remote는 별도 repo (Job-bizgov-platform vs Job_bizgov_platform_dev). cherry-pick은 second remote 추가 + fetch 후 진행.

## 배포 상태
- [x] v2 commit 완료 (25522fec, 2026-05-04)
- [x] v1 운영 환경변수 적용 완료 (DB_PATH=/var/data/biz.db)
- [x] v1 운영 영구 disk 전환 완료 (Persistence test 통과)
- [ ] v1 cherry-pick (대기)
- [ ] v1 검증 (대기)
- [ ] v1 push (대기)
- [ ] Render 재검증 (대기)
- [ ] v2 .gitignore 추적 해제 (Phase 3 대기)
- [ ] v1 .gitignore 추적 해제 (Phase 3 대기)
