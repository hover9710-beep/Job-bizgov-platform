# 배포 기록 템플릿 / 이력

## 2026-05-06 배포
- Commit: `788e54a`
- 영향 파일: `appy.py` 1개
- 변경 영역: 함수 1개 교체 + 라우트 1줄화 2곳 + GROUP BY 1줄
- 변경 의도: "오늘 가장 많이 본 공고" 위젯을 필터 무관 전역 집계로 분리 + SQL ambiguous column 수정
- 사전 검증: 로컬 4 URL 시나리오 (/와 /?site=jbtp, /?site=jbexport, /new) 동일 항목 표시 확인
- 배포 방식: GitHub push → Render 자동 배포
- 롤백 지점: `bc1c44b85157a540356c1792cff87681562af245`
- 사후 검증: 라이브 4 URL 동일 표시 확인 완료
- 사고: 없음

## 배포 체크리스트 (다음 배포 시 사용)

### 사전
- [ ] 로컬 검증 완료 (`py appy.py` 테스트)
- [ ] 테스트 데이터 정리 (`DELETE WHERE title LIKE '테스트%'`)
- [ ] git status 깨끗 (modified는 의도된 파일만)
- [ ] 롤백 지점 해시 메모 (`git rev-parse HEAD`)

### 진행
- [ ] git add + commit (사용자 직접)
- [ ] git push origin main (사용자 직접)
- [ ] Render Events 탭에서 "Deploy started" 확인
- [ ] Render Events 탭에서 "Deploy live" 도달 확인 (1-3분)

### 사후
- [ ] 라이브 4 URL 검증
- [ ] 운영 사용자 영향 모니터링 (5-10분)
- [ ] daily/ 로그 작성
- [ ] deploy_template.md에 entry 추가

### 사고 시
- 즉시: `git reset --hard <롤백해시> && git push origin main --force-with-lease`
- 30초 안에 Render 이전 버전으로 자동 재배포

