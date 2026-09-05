# Progream — 일본 유튜브 영상 자동화 도구 모음

비개발자 사용자를 위한 저장소다. 응답은 쉬운 한국어로, 명령어·코드 노출은 최소화할 것.

## 프로그램 구성

| 파일 | 역할 | 실행 |
|---|---|---|
| `japan_review.py` (+`video_check.py`) | 프로젝트 폴더(대본·이미지·자막·mp4) 검토 → `검토리포트.html` | `review.bat` |
| `video_builder.py` | 씬별 제미나이 TTS → 자막/타임라인 → 캡컷 초안 자동 생성 | `자동배치.bat` |
| `tts_test.py` | 목소리 6종 샘플 생성 (API 키 최초 등록도 여기서) | `tts_test.bat` |
| `naver_capture.py` | 네이버 카페 글 캡쳐 (별개 프로그램) | `capture.bat` |

- "일본 캡컷 자동화 해줘" → `.claude/skills/japan-capcut-automation` 스킬이 전체 흐름을 정의한다.
- 프로젝트 폴더 규격: 파일명에 `대본`이 든 .txt + `06_scene-mapping.txt` + `images/001.png...`
  (씬 수 = 이미지 수). `자동배치` 실행 결과는 폴더 안 `출력/`에 생긴다.
- 비대화형 실행: `python video_builder.py <폴더> --voice Gacrux --speed 느리게 [--draft-dir 경로]`
- 검토 비대화형: `python japan_review.py <폴더> --no-open`

## 주의

- `api_key.txt`(제미나이 키), `builder_config.json`, `browser_profile/`은 절대 커밋·출력 금지 (.gitignore 처리됨).
- 캡컷 초안 생성은 pycapcut 기반, 사용자 캡컷은 9.3.0 (배경: `캡컷연동_준비메모.md`).
- 테스트는 모의 TTS로: `tts_with_retry`를 바꿔치기하면 API 키 없이 전체 흐름 검증 가능.
