# 백로그 047 + 048 운영(Render) 적용 절차

대상 파일: `docs/render_sql/b047_b048_followup.sql`
적용 위치: Render 운영 DB `/var/data/biz.db`

## 사전 확인 (Render Shell)

```bash
# 1) auto-deploy 완료 확인 (커밋 7de79e5 가 반영되었는지)
cd /opt/render/project/src && git log -1 --oneline
# → "7de79e5 fix(jbexport): selector 교체 + status sync 추가 (백로그 047 + 048)" 가 보여야 함

# 2) SQL 파일 존재 확인
ls -la docs/render_sql/b047_b048_followup.sql
# → 5,487 bytes 정도

# 3) 운영 DB 위치 확인
ls -la /var/data/biz.db
sqlite3 /var/data/biz.db "SELECT COUNT(*) FROM biz_projects WHERE source='jbexport';"
# → 운영은 12,139 부근 (jbexport 단일 source 만 별도 카운트)
```

## 백업

```bash
cp /var/data/biz.db /var/data/biz.db.backup_b047_b048_$(date +%Y%m%d_%H%M%S)
ls -la /var/data/biz.db.backup_b047_b048_*
```

## 적용 전 baseline (정정 대상 8 row 의 BEFORE 상태 기록)

```bash
sqlite3 /var/data/biz.db <<'EOF'
.mode column
.headers on
SELECT id, status, raw_status, SUBSTR(title,1,40) AS title
FROM biz_projects
WHERE source='jbexport' AND (
  url LIKE '%spSeq=4f3a1a39967a49148b031d6416e55614%' OR
  url LIKE '%spSeq=9fbace94ea0e48e4a2e7bcb9829f24a4%' OR
  url LIKE '%spSeq=9810ffef21cf4e869be5e38df525e408%' OR
  url LIKE '%spSeq=eb876dda1c7949f3b10e0e29685b5b43%' OR
  url LIKE '%spSeq=8260a0d42d444760a0fd2428237c9393%' OR
  url LIKE '%spSeq=c02eb9e7bf2441f68603a890510b95a4%' OR
  url LIKE '%spSeq=1d902514a6b4485795440bee26e22231%' OR
  url LIKE '%spSeq=8d9b66c907344f97a3efa214228e7722%'
)
ORDER BY id;
EOF
```

## 적용

```bash
sqlite3 /var/data/biz.db < docs/render_sql/b047_b048_followup.sql
```

(파일이 BEGIN/COMMIT 으로 감싸져 있어 atomic 하게 적용됨.)

## 적용 후 검증

```bash
# 1) baseline 명령 다시 실행 — 모든 row 가 사이트 진실로 정정되었는지 확인
# (위 baseline SQL 다시 실행)

# 2) 신규 INSERT 2건 확인
sqlite3 /var/data/biz.db <<'EOF'
SELECT id, status, raw_status, SUBSTR(title,1,50) AS title
FROM biz_projects
WHERE source='jbexport' AND (
  url LIKE '%spSeq=93b55df14467448399e310540eab2e98%' OR
  url LIKE '%spSeq=20338576de7c4bdeb817ef63f2d8b3bd%'
);
EOF
# → 각각 1 row 보여야 함

# 3) 전체 카운트 변동 (백필이 row 수 안 바꾸고, INSERT 2건만 +)
sqlite3 /var/data/biz.db "SELECT COUNT(*) FROM biz_projects WHERE source='jbexport';"
# → BEFORE + 2 (운영 DB 가 신규 2 row 를 이미 들고 있지 않다면)
```

## 기대 결과

| 카테고리 | 변동 |
|---|---|
| 백로그 047 백필 (4 row) | title / start_date / end_date / period_text 정정 |
| 백로그 048 status (4 row) | status 진행 → 마감, raw_status 접수중/공고중 → 접수마감 |
| 신규 INSERT (2 row) | url unique 제약 → 이미 있으면 NOT EXISTS 가드로 skip |

## 롤백

```bash
# 백업으로 복원
mv /var/data/biz.db /var/data/biz.db.failed_$(date +%Y%m%d_%H%M%S)
cp /var/data/biz.db.backup_b047_b048_<timestamp> /var/data/biz.db
```

## 주의

- biz_projects 의 mirror 테이블 `projects` 는 update_db 의 mirror_projects 에서 재생성되므로 손대지 않아도 됨
- redis / cache 가 있다면 별도 invalidate 필요 (현재 없는 것으로 보임)
- 다음 daily run (Render 자동 daily 또는 수동 trigger) 부터는 백로그 048 코드 fix 가 active 이므로 status stale 이 더 안 발생
