# JB BizGov Platform

전북·중앙 공고 데이터를 수집·병합하고, 신규 공고를 비교한 뒤 메일 본문 초안을 만드는 도구 모음입니다.

## 주요 기능

- **JBEXPORT / BIZINFO** 공고 수집
- **전체 JSON 병합** (`merge_sources`)
- **신규 공고 비교** (`diff_new` — `today` vs `yesterday` 스냅샷)
- **메일 본문 생성** (`make_mail`)

## 실행 순서 (예시)

프로젝트 루트에서:

```bash
python pipeline/diff_new.py
python pipeline/make_mail.py
```

병합·크롤은 기존 파이프라인(`merge_sources`, `jbexport_daily`, 커넥터 등)에 맞춰 실행합니다.

## 데이터 스키마
- [ROW Schema v1](pipeline/ROW_SCHEMA.md) — row 표준계약서 (필드 정의 / status 규칙 / 금지사항)

## 출력 파일

| 경로 | 설명 |
|------|------|
| `data/all_sites.json` | 병합된 전체 공고 목록 |
| `data/new.json` | 신규로 판정된 항목 |
| `data/mail/mail_body.txt` | 메일 본문 초안 |

> 로컬 `data/` 는 `.gitignore`로 제외되는 경우가 많습니다. 저장소에는 샘플·문서만 두고, 실제 JSON은 실행 환경에서 생성합니다.

## 원격 저장소

- GitHub: `hover9710-beep/Job-bizgov-platform` (`main`)
