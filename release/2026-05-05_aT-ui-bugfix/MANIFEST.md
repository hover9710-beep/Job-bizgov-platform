# 배포확정: 2026-05-05 AT 공고 UI 버그 2건 수정

## 마감 정보
- 마감일: 2026-05-05
- 작업자: 김형식 (Cursor AI 지원)
- v2 base commit: 작업 직전
- 관련 이슈: AT(at_global) 공고 UI 버그 2건

## 버그 원인 분석

### 버그 2 (버튼 겹침) 원인
- `<td class="action-col card-actions">` 에 `display: flex + overflow: hidden` 적용
- AT공고는 `ai_summary`, `recommend_label`, `recommend_reason`이 없어 title 셀이 짧음
- → 행 높이가 낮게 계산됨 → `overflow: hidden` 으로 두 번째 버튼이 클리핑됨
- `all: revert !important` CSS도 예상치 못한 동작 유발

### 버그 1 (상세 페이지 깨짐) 원인
- "✔ 전북 기업 대상 / 지원사업" 텍스트가 AT (전국 대상) 공고에 부적절
- "👉 공식 페이지 바로 신청" 버튼 레이블이 AT 공고 맥락에 맞지 않음
  (AT 공고는 신청이 아닌 공고 원문 확인 목적)
- AT 상세 안내 문구 없음 (HWP/PDF 첨부 파일 안내)

## 변경 요약
AT 공고 특성에 맞게 UI를 수정. 다른 source 공고에는 영향 없음.

## 영향 파일 (4개)

### 1. `templates/new.html` (+3줄)
**변경 내용**: 액션 컬럼 구조 개선 - `<td>` 대신 `<div>` 를 flex 컨테이너로 사용

```html
<!-- 이전 -->
<td class="action-col card-actions">
    <a class="btn-detail" ...>공고 자세히 보기</a>
    ...
</td>

<!-- 이후 -->
<td class="action-col">
    <div class="card-actions">
        <a class="btn-detail" ...>공고 자세히 보기</a>
        ...
    </div>
</td>
```

**효과**: td 높이가 자연스럽게 버튼 높이에 맞게 확장, overflow 클리핑 방지

### 2. `templates/_new_list_page_styles.html` (수정)
**변경 내용**:
- `.card-actions` 에서 `overflow: hidden !important` 제거 (클리핑 원인)
- `.card-actions a` 에서 `all: revert !important` 제거 (예측 불가 동작 원인)
- 명시적 CSS 속성으로 교체 (`text-decoration: none`, `cursor: pointer` 등)
- `white-space: nowrap` → `white-space: normal` (긴 텍스트 줄 바꿈 허용)
- `.action-col.card-actions` → `.action-col .card-actions` (새 구조에 맞게)
- PC 미디어쿼리 동일 업데이트

### 3. `templates/project_detail.html` (수정)
**변경 내용**:
- `cta-sub` 텍스트 source 조건 분기:
  - `at_global`: "✔ 농수산식품 수출기업 / 전국 대상 사업"
  - 그 외: "✔ 전북 기업 대상 / 지원사업" (기존 유지)
- CTA 버튼 텍스트 source 조건 분기:
  - `at_global`: "📋 공고 원문 보기 (aT 공식 사이트)"
  - 그 외: "👉 공식 페이지 바로 신청" (기존 유지)
- AT 공고 안내 문구 추가: "aT 공식 사이트로 이동. 공고문·첨부 파일(HWP/PDF)은 해당 페이지에서 확인"
- 제목 `.detail-title-text` 에 `word-break: keep-all; overflow-wrap: break-word` 추가

### 4. `appy.py` + `pipeline/ui_view.py` (SOURCE_LABELS 확장)
**변경 내용**: 소스 라벨 맵핑 추가
```python
SOURCE_LABELS = {
    ...
    "jbtp": "전북TP",         # 기존 누락
    "jbbi": "전북바이오",     # 기존 누락
    "jbtp_related": "JBTP유관",  # 기존 누락
    "at_global": "aT글로벌",  # 신규 추가
}
```

## 다른 source 영향
- 없음. 조건 분기는 `source == 'at_global'` 에만 적용
- CSS 변경사항(overflow, all:revert 제거)은 모든 소스에 적용되지만
  기존에 정상 동작하던 소스에는 영향 없음 (flex column 구조 동일 유지)

## v1 적용 방법

### 빠른 적용 (수동 diff)
변경 파일 4개를 v1에 동일 적용:

```bash
# 1. v1 backup
cp -r C:\Users\custo\OneDrive\바탕화면\커서앱통합_v1 C:\Users\custo\OneDrive\바탕화면\커서앱통합_v1_백업_cherry_pick_2026-05-05-ui

# 2. templates 복사 (3개)
cp templates\new.html ..\커서앱통합_v1\templates\new.html
cp templates\_new_list_page_styles.html ..\커서앱통합_v1\templates\_new_list_page_styles.html
cp templates\project_detail.html ..\커서앱통합_v1\templates\project_detail.html

# 3. appy.py SOURCE_LABELS 수동 수정 (v1\appy.py 395~399행)
# 4. pipeline\ui_view.py SOURCE_LABELS 수동 수정 (v1\pipeline\ui_view.py 49~53행)
```

### 검증 절차
1. `py appy.py` 로컬 실행
2. 브라우저 `http://localhost:5000` → AT 탭 필터 클릭
3. AT 공고 카드 확인: 버튼 2개 정상 표시 (겹침 없음)
4. AT 공고 클릭 → 상세 페이지: "aT 공식 사이트" 버튼, 전국 대상 텍스트 확인
5. 다른 source (bizinfo, jbexport) 공고 정상 표시 확인

## 배포 상태
- [x] v2 수정 완료
- [x] v2 push 완료 (commit 476f22e)
- [x] v1 적용 완료 (2026-05-05)
- [x] v1 byte-identical 검증 완료
- [ ] v1 push (대기 — 사용자 직접)
- [ ] Render 배포 확인 (대기)

## v1 적용 결과 (2026-05-05)

### 적용 방식
- templates 3개: v2 → v1 단순 복사 (Copy-Item -Force)
- appy.py + pipeline/ui_view.py: SOURCE_LABELS 영역만 부분 Edit (4줄 추가)
- release/2026-05-05_aT-ui-bugfix/ 사본 v1로 복사

### v1 git diff --stat
```
 appy.py                              |  4 +++
 pipeline/ui_view.py                  |  4 +++
 templates/_new_list_page_styles.html | 64 +++++++++++++++++-------------------
 templates/new.html                   |  4 ++-
 templates/project_detail.html        | 17 ++++++++++
 5 files changed, 59 insertions(+), 34 deletions(-)
```

→ v2 commit 476f22e의 stat과 정확히 일치 (180 insertions, 34 deletions).

### v2/v1 byte-identical 검증 (md5)
- templates/_new_list_page_styles.html: SAME `4D61C0ACFEB742F2044ADFE4C255EA22`
- templates/new.html: SAME `B2F55F820302D2C8F336BCDA6F15F345`
- templates/project_detail.html: SAME `8995BCAB32B25D976FD520866F34B968`
- pipeline/ui_view.py: SAME `08B8E58B74E5F83BB95C0D0F138A24D8`
- release/.../MANIFEST.md: SAME `4A709CE4C8F9B28876DBAE0037E8C565` (v1 적용 결과 섹션 추가 전 기준)
- appy.py: 백로그 027 변경분(SOURCE_LABELS 4줄)은 정확히 동일하나, v2에는 별도 백로그(check_admin/is_admin) 변경분이 추가로 존재 → 이번 백로그 027 범위 밖이므로 v1에 반영 안 함

## 롤백 방법
- git revert (v2 commit 단위)
- 또는 수동: `_new_list_page_styles.html` 의 `card-actions` CSS 복원
