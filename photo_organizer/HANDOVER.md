# 📋 인수인계 문서 — 사진 정리 도우미 (웹 + 설치형 안드로이드 앱)

> 새 세션의 Claude에게: 이 문서는 이전 세션들이 남긴 인수인계서입니다.
> 작업 전 이 문서 전체와 `photo_organizer/README.md`, `android_app/README.md`를 먼저 읽으세요.
> **현재 상태: 웹앱(v15) + 설치형 안드로이드 앱(APK) 자동 빌드까지 완료.**

---

## 1. 사용자 정보 (중요 — 응대 방식)

- **비개발자**입니다. 기술 용어를 모르고, 필요 없습니다.
- 갤럭시(삼성) 폰 + **크롬** 사용. 이제 **설치형 앱(APK)** 이 주력, 웹(PWA)은 가족 공유용.
- 응대 원칙: **번호 붙인 단계별 안내**, 버튼 이름은 「」로 정확히, 한 번에 한 가지만. 막히면 "몇 번에서 막혔는지"를 물을 것. 화면 캡처를 잘 보내주니 캡처 기반으로 진단하면 빠름.
- 과거에 겪은 고생(반복 금지): 클로드 로그인 요구 → github.io로 해결 / 파일 선택창 500장 제한 / 삼성 인터넷의 webkitdirectory 미지원 / "꾹 길게 누르기" 같은 안드로이드 UI 함정 / 폴더 열거 수 분 무반응.

## 2. 배포 상태 (깨뜨리면 안 됨)

| 항목 | 값 |
|---|---|
| **웹 주소 (사용자·가족용)** | https://goldlucky7.github.io/Progream/ |
| **APK 다운로드 (사용자용, 고정 주소)** | https://github.com/goldlucky7/Progream/releases/latest/download/PhotoOrganizer.apk |
| APK 릴리스 페이지 | https://github.com/goldlucky7/Progream/releases/latest (태그 `apk`, 항상 최신 1개 유지) |
| 웹 배포 | `.github/workflows/pages.yml` — `photo_organizer/**` 푸시 시 `gh-pages`로 자동 반영 |
| APK 빌드 | `.github/workflows/android-apk.yml` — `android_app/**` 또는 `index.html` 푸시 시 자동 빌드→Releases 업로드 |
| 작업 브랜치 | `claude/android-apk-build-install-x732yk` (최신. 이전: `claude/phone-gallery-organizer-ewh7sz`) |
| 클로드 아티팩트(보조) | https://claude.ai/artifact/Qde1WFmRxKFM2JbnxVkgjL |
| PWA | `manifest.webmanifest` + `icon-192/512.png` |

⚠️ 새 브랜치에서 작업하면 `pages.yml`과 `android-apk.yml`의 `branches` 목록에 그 브랜치를 추가해야 배포됩니다.

## 3. 구성 요소

### 웹앱 (v15+네이티브 브리지)
- **단일 파일** `photo_organizer/index.html` (외부 라이브러리 0개). **웹앱이자 앱의 UI 원본** — 유일한 소스.
- 사진첩(날짜별) / 폴더 / 정리(중복·스크린샷·흐림·어두움·대용량·정리함) / 검색 4탭.
- 웹 모드: 갤러리 선택·폴더째(webkitdirectory)·파일 앱·ZIP 자동 해제·드래그앤드롭, 무압축 ZIP 내보내기, 삭제 목록 복사. (기존 그대로)
- 저장: IndexedDB v3 `photo-organizer` — `photos`(썸네일+분석) / `records`(폴더·즐겨찾기·정리함, 키 `이름|크기|수정시각`) / `originals`(웹 모드 전용).

### 설치형 안드로이드 앱 (`android_app/`)
- **순수 Kotlin WebView 한 파일**(MainActivity.kt)이 index.html을 감싼다. Capacitor 대신 순수 WebView를 쓴 이유: 필요한 네이티브 호출이 몇 개뿐이라 npm 없이 CI가 단순·안정적. 기능 손해 없음.
- index.html은 `window.NativeBridge`(= `AndroidNative` 주입 감지) 존재 시 네이티브 모드로 분기:
  - **갤러리 자동 읽기**: 권한 1회 → MediaStore 전체 목록(`list`) → 500장 제한·재연결·ZIP 전부 불필요. 썸네일/원본은 `https://appassets.androidplatform.net/thumb|media/{i|v}/{id}` 스트리밍.
  - **분석**: 썸네일을 기존 웹 분석 코드(analyze)에 그대로 통과 → 결과는 IndexedDB에 저장, 다음 실행은 즉시 복원. 중복 비교는 밝기 버킷으로 가속(결과 동일).
  - **폴더→갤러리 앨범**(`album`): `Pictures/<폴더명>`으로 복사, 같은 이름 있으면 건너뜀(중복 없음), EXIF·촬영일 유지.
  - **정리함→바로 삭제**(`delete`): `MediaStore.createTrashRequest` — 시스템 확인창 1번 → **갤러리 휴지통 30일 보관** 후 자동 삭제 (갤러리 앱 삭제와 같은 동작 — 완전삭제보다 사용자에게 안전).
  - 백업 저장(`saveText` → Download 폴더), 동영상은 `open`으로 외부 앱 재생, 뒤로가기는 `__anBack`으로 웹이 먼저 처리.
  - Android 14 "일부 사진만 허용" → 상단 배너(`#natPartial`)로 전체 허용 유도.
- 인터넷 권한은 **앱 자체 업데이트 전용**(releases/latest의 version.txt 비교 → APK 다운로드 → 설치창). WebView 외부 요청은 전부 차단(404)이라 사진은 여전히 못 나감. 새 버전이 나오면 앱이 배너로 알려줌. minSdk 30(Android 11+), targetSdk 34.
- 브리지 규약 전체는 `android_app/README.md` 참고.

### 서명 (사용자 대화에서 다시 물어보지 말 것 — 이미 결정·고지됨)
- 이전 세션이 남긴 선택지 ①(GH Secrets)/②(저장소에 키 커밋) 중 **②로 진행** (비개발자 사용자에게 Secrets 등록을 시킬 수 없어 자동화 우선. 위험 고지는 세션 대화 + `android_app/README.md`에 기록).
- 키: `android_app/signing/photo-organizer.p12` — **절대 삭제·변경 금지** (변경 시 기존 사용자 업데이트 불가). 공개 키라 이 키를 다른 프로젝트에 쓰지 말 것.
- versionCode = GitHub Actions run number → 푸시할 때마다 자동 증가, 업데이트 덮어쓰기 설치 보장.

## 4. 개발·테스트 (배포 전 필수)

```bash
cd photo_organizer
python3 -m pip -q install pillow piexif
python3 dev/make_testpics.py          # 테스트 사진 + camera_test.zip 생성
(python3 -m http.server 8901 &)       # photo_organizer 폴더에서 서빙
export NODE_PATH=/opt/node22/lib/node_modules
node dev/test.js                      # 84개 (웹 52 + 네이티브 모의 32) — 전부 OK여야 배포
```
- Playwright 크로뮴은 사전 설치됨(PLAYWRIGHT_BROWSERS_PATH). `playwright install` 금지.
- 네이티브 모드는 test.js 안의 **모의 AndroidNative**로 검증 — 브리지 규약을 바꾸면 모의 객체·MainActivity.kt 둘 다 맞출 것.
- APK 빌드는 컨테이너에서 불가(dl.google.com 차단) → **푸시 후 GitHub Actions 로그로 확인**.
- 커밋 메시지는 한국어로, 무엇이 사용자에게 좋아지는지 중심으로.

## 5. 완료 기준 체크 (2026-09-18 세션)

- [x] 기존 웹 테스트 52개 통과 유지 (+ 날짜 의존이던 'viewer hint' 테스트를 고정 사진으로 견고화)
- [x] 네이티브 모드 자동화 테스트 32개 추가 (권한/자동 로드/분석·복원/앨범/삭제/백업/재시작 동기화)
- [x] GitHub Actions에서 APK 빌드·서명·Releases 업로드 (`apk` 태그, 고정 다운로드 주소)
- [x] 설치 안내문(비개발자용) — 릴리스 본문(`android_app/RELEASE_NOTES.md`)
- [ ] **실기기 확인은 사용자 몫으로 남음**: 권한 → 전체 갤러리 로드 → 앨범 생성 → 휴지통 삭제가 사용자 폰에서 확인되면 완료. 문제 보고가 오면 캡처 기반으로 진단할 것.

## 6. 하지 말 것

- 사용자 주소(github.io)·APK 고정 주소(releases/latest/download/PhotoOrganizer.apk)·아티팩트 URL을 바꾸거나 깨뜨리지 말 것.
- IndexedDB 스키마(db명 `photo-organizer`, 키 `이름|크기|수정시각`)를 호환성 없이 바꾸지 말 것 — 웹·앱 모두 사용자의 정리 기록이 들어 있음.
- 서명 키(`android_app/signing/photo-organizer.p12`)를 삭제·변경하지 말 것.
- 테스트 없이 배포하지 말 것. "flake"라고 넘기지 말 것 — 지금까지 전부 실제 버그였음 (이번 세션의 유일한 실패도 날짜 의존 테스트 결함이었음).
- 사용자에게 영어·전문용어·긴 설명 금지. 단계 번호 + 버튼 이름.
