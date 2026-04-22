# BizGovPlanner Row 표준계약서 v1
## 기본 원칙
1. row는 항상 dict 형태
2. 빈값은 None 아닌 "" 로 통일
3. 핵심 필드명 절대 변경 금지
4. start_date <= end_date 보장
5. status 생성은 infer_status() 단일 진입점만 사용

## 필드 정의
| 필드명 | 타입 | 허용값 | 비고 |
|--------|------|--------|------|
| id | int | - | DB PK |
| title | str | 필수 | 공고명 |
| source | str | jbexport/bizinfo/kstartup | unknown 금지 |
| organization | str | "" 허용 | 수행기관 |
| ministry | str | "" 허용 | 소관부처 |
| start_date | str | YYYY-MM-DD 또는 "" | |
| end_date | str | YYYY-MM-DD 또는 "" | start_date <= end_date 보장 |
| period_text | str | raw 원문 그대로 | 소스별 공급원 다름 |
| status | str | 접수중/마감/확인 필요 | infer_status() 결과만 |
| url | str | 필수 | 공고 원문 링크 |
| description | str | "" 허용 | |
| collected_at | str | YYYY-MM-DD HH:MM:SS | 수집일시 |

## period_text 소스별 공급원
| source | 공급원 |
|--------|--------|
| bizinfo | parse_bizinfo_dates() 라벨 매칭 원문 (접수기간>신청기간>모집기간>사업기간>공고기간>기간) |
| jbexport | period 필드 raw 값 |
| kstartup | 목록 li 원문 텍스트 |

## status 계산 규칙
pipeline/normalize_project.py infer_status() 참조
1. end_date 있으면 날짜 기준
2. 없으면 period_text 키워드 (상시/접수중/예산소진→접수중, 마감/종료→마감)
3. 불명확 → 확인 필요

## 파이프라인별 사용
| 파이프라인 | 파일 | 역할 |
|-----------|------|------|
| 수집/저장 | connectors/* → normalize_project.py → update_db.py | row 생성 |
| 메일 | mail_view.py | 신규/마감임박/접수중 필터 |
| UI | ui_view.py | 전체목록/정렬/필터 |

## 금지사항
- presenter.py에서 status 직접 생성 금지
- source = unknown 저장 금지
- end_date < start_date 저장 금지
- None과 "" 혼용 금지 (항상 "" 통일)
