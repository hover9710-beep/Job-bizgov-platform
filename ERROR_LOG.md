# BizGovPlanner 오류 로그

AI 에이전트가 이 파일을 읽고 과거 오류와 해결책을 참고하여 동일한 오류를 재현하지 않도록 한다.

## 포맷
- **증상**: 화면에 어떻게 보였는가
- **원인**: 실제 코드/환경 원인
- **해결**: 적용한 해결책
- **파일**: 수정한 파일명
- **재발 방지**: 다음에 동일 상황 시 바로 적용할 것

---

### [2026-05-01] /new 화면 접수중 0 버그
- **증상**: /new 화면에서 접수중 0, 마감 175, 확인 필요 29로 표시됨. DB에는 접수중 498건 존재.
- **원인**: _render_new_announcements_page()에서 `from pipeline.normalize_project import infer_status` 실행 시 Render 환경에 pipeline 모듈 없어서 ImportError 발생. except 블록에서 rows=[]로 조용히 처리되어 화면 0건 표시.
- **해결**: try/except로 import 감싸고 ImportError 시 end_date 기반 fallback 함수 _infer_status() 직접 정의.
- **파일**: appy.py (_render_new_announcements_page 함수)
- **재발 방지**: Render 배포 시 pipeline 모듈 import는 반드시 try/except로 감싸거나 fallback 제공. Render에는 pipeline/ 폴더가 없을 수 있음.

---

### [2026-05-01] 카카오 공유 Error 4019
- **증상**: 상세페이지에서 카카오 공유 버튼 클릭 시 Error 4019 발생
- **원인**: Kakao.init()에 잘못된 키 사용 (REST API 키 또는 오타 있는 JS 키). JS 키는 32자여야 하는데 31자로 입력됨.
- **해결**: 올바른 JS 키(7c482b7b3b3dc493ee01532cbc3f31e6) 사용. kakao.min.js를 </body> 바로 위에 배치. DOMContentLoaded 후 init 실행.
- **파일**: templates/project_detail.html
- **재발 방지**: 카카오 JS 키는 반드시 32자 확인. REST API 키(f5e26b...)는 Kakao.init에 절대 사용 금지. imageUrl 없으면 제거.

---

### [2026-04-xx] DB 소실 및 복구
- **증상**: /new 화면 전체 0건. db/biz.db 없거나 비어있음.
- **원인**: 라우트 수정 중 DB 파일 삭제 또는 덮어써짐. 백업 폴더에서 복구 필요.
- **해결**: 백업폴더(커서앱통합_개발자용_0501)에서 db/biz.db 복사 후 git add -f db/biz.db → push → Render 재배포.
- **파일**: db/biz.db
- **재발 방지**: DB 수정 전 항상 백업. db/biz.db는 .gitignore에서 제외하여 GitHub에 포함 유지.

---

### [2026-05-01] JBBI 커넥터 region 컬럼 오류
- **증상**: connector_jbbi.py 실행 시 `table biz_projects has no column named region` 오류
- **원인**: save_to_db() INSERT 구문에 존재하지 않는 region 컬럼 사용. v2 DB에는 region 없고 site 컬럼 사용.
- **해결**: INSERT 컬럼을 실제 DB 스키마 기준으로 수정. region → site 변경.
- **파일**: connectors/connector_jbbi.py
- **재발 방지**: 새 커넥터 작성 시 반드시 PRAGMA table_info(biz_projects)로 실제 컬럼 확인 후 INSERT 작성.

---
