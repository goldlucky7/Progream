# 📋 인수인계 문서 — 사진 정리 도우미 → 설치형 안드로이드 앱

> 새 세션의 Claude에게: 이 문서는 이전 세션이 남긴 인수인계서입니다.
> **다음 임무: 이 웹앱을 설치형 안드로이드 앱(APK)으로 만드는 것.**
> 작업 전 이 문서 전체와 `photo_organizer/README.md`를 먼저 읽으세요.

---

## 1. 사용자 정보 (중요 — 응대 방식)

- **비개발자**입니다. 기술 용어를 모르고, 필요 없습니다.
- 갤럭시(삼성) 폰 + **크롬** 사용 (삼성 인터넷은 폴더 불러오기가 안 되어 크롬으로 정착).
- 홈 화면에 PWA로 설치해서 쓰는 중.
- 응대 원칙: **번호 붙인 단계별 안내**, 버튼 이름은 「」로 정확히, 한 번에 한 가지만. 막히면 "몇 번에서 막혔는지"를 물을 것. 화면 캡처를 잘 보내주니 캡처 기반으로 진단하면 빠름.
- 과거에 겪은 고생(반복 금지): 클로드 로그인 요구 → github.io로 해결 / 파일 선택창 500장 제한 / 삼성 인터넷의 webkitdirectory 미지원 / "꾹 길게 누르기"·"모두 선택은 한 장 선택 후 나타남" 같은 안드로이드 UI 함정 / 폴더 열거가 수 분 걸리는 동안의 무반응.

## 2. 현재 배포 상태 (깨뜨리면 안 됨)

| 항목 | 값 |
|---|---|
| **사용자가 쓰는 주소** | https://goldlucky7.github.io/Progream/ |
| 배포 방식 | `.github/workflows/pages.yml` — `photo_organizer/**` 푸시 시 `gh-pages` 브랜치로 자동 반영 (peaceiris/actions-gh-pages) |
| 작업 브랜치 | `claude/phone-gallery-organizer-ewh7sz` (모든 코드가 여기 있음, 기본 브랜치에 **미병합**) |
| 클로드 아티팩트(보조) | https://claude.ai/artifact/Qde1WFmRxKFM2JbnxVkgjL — 새 세션에서는 Artifact 도구에 `url`로 이 주소를 넘기면 갱신 가능 |
| PWA | `manifest.webmanifest` + `icon-192/512.png` (딥틸 사진 아이콘) |

⚠️ 새 브랜치에서 웹 버전을 고치면 `pages.yml`의 `branches` 목록에 그 브랜치를 추가해야 사이트에 반영됩니다.

## 3. 웹앱 현재 기능 (v15, 테스트 52개 전부 통과)

- **단일 파일** `photo_organizer/index.html` (~120KB, 외부 라이브러리 0개). 이 파일이 유일한 소스.
- 사진첩(날짜별) / 폴더(사용자 앨범, 구 '테마') / 정리(중복·스크린샷·흐림·어두움·대용량·정리함) / 검색 4탭.
- 불러오기: 갤러리 선택, **폴더째(webkitdirectory)**, 파일 앱(무필터 input), **ZIP 자동 해제**(자체 리더: ZIP64·EUC-KR·스트리밍), 드래그앤드롭.
- 분석: EXIF 촬영일 자체 파서, 가로+세로 dHash+밝기로 중복 그룹, 라플라시안 분산(중앙값 상대 기준) 흐림, FaceDetector 있으면 인물 자동.
- 저장: IndexedDB v3 — `photos`(썸네일+분석) / `records`(폴더·즐겨찾기·정리함) / `originals`(**폴더에 담은 사진의 원본 blob**, 250MB 초과 제외). 껐다 켜면 전체 복원, 같은 파일 재선택 시 원본만 재연결(중복 없음).
- 내보내기: 폴더 → **무압축 ZIP(자체 라이터, CRC32)** 다운로드 → 내 파일에서 압축 해제 → 갤러리에 실제 앨범. 삭제는 목록 복사 방식(브라우저 한계).
- 백업: 정리 기록 JSON 내보내기/불러오기. 아티팩트 환경에선 `downloads` capability(`window.claude.use("downloads")`), 아니면 앵커 다운로드/클립보드 폴백.

## 4. 개발·테스트 방법 (이 저장소 안에 다 있음)

```bash
cd photo_organizer
python3 -m pip -q install pillow piexif
python3 dev/make_testpics.py          # 테스트 사진 + camera_test.zip 생성
(python3 -m http.server 8901 &)       # photo_organizer 폴더에서 서빙
export NODE_PATH=/opt/node22/lib/node_modules   # playwright 전역 설치 경로
node dev/test.js                      # 52개 검사 — 전부 OK여야 배포
```
- Playwright 크로뮴은 이 환경에 사전 설치돼 있음(PLAYWRIGHT_BROWSERS_PATH). `playwright install` 금지.
- **index.html을 고치면 반드시 test.js를 돌려서 전부 통과한 뒤** 커밋·푸시할 것. 커밋 메시지는 한국어로, 무엇이 사용자에게 좋아지는지 중심으로.

## 5. 다음 임무: 설치형 안드로이드 앱 (APK)

### 목표 (사용자와 합의된 것)
1. 갤러리를 **권한 한 번 받고 자동으로** 읽기 — 사진 선택/500장 제한/재연결 전부 제거
2. 폴더 정리하면 **갤러리에 실제 앨범 자동 생성** (zip 수동 해제 제거)
3. 정리함 → **앱에서 바로 삭제** (시스템 확인창 1번)
4. 비용 0원: APK 직접 설치 (플레이스토어 등록 안 함)

### 권장 설계 (이전 세션의 조사 결과)
- **Capacitor**로 기존 `index.html` UI를 그대로 감싸고, 작은 Kotlin 플러그인 하나 추가:
  - `listGallery()` → MediaStore 쿼리: `{id, uri, name, size, dateTaken(DATE_TAKEN), mime, w, h, duration}` 배열. 수천 장도 1~2초.
  - `getThumb(uri, size)` → `ContentResolver.loadThumbnail()` (JS 썸네일 파이프라인보다 훨씬 빠름). dHash/흐림 분석은 이 썸네일 비트맵을 JS로 넘겨 기존 코드 재사용.
  - `createAlbum(name, uris[])` → `MediaStore.Images` insert + `RELATIVE_PATH = "Pictures/<name>"`로 복사 (또는 `createWriteRequest`로 이동).
  - `deleteMedia(uris[])` → `MediaStore.createDeleteRequest()` — 시스템이 일괄 확인창 1번 띄움. 이게 "앱에서 바로 삭제"의 정답.
  - 권한: `READ_MEDIA_IMAGES`, `READ_MEDIA_VIDEO` (API 33+), 하위 버전은 `READ_EXTERNAL_STORAGE`.
- 웹 코드에는 `window.NativeBridge` 존재 여부로 분기: 있으면 불러오기 버튼들 대신 "갤러리 자동 읽기", 내보내기 대신 `createAlbum`, 삭제 목록 대신 `deleteMedia`. **웹 버전은 그대로 살려둘 것** (가족 공유용).
- 원본 IndexedDB 보관(`originals`)은 네이티브에선 불필요 — uri로 항상 접근 가능.

### 빌드·전달
- GitHub Actions로 APK 빌드 (ubuntu + JDK17 + gradle), **Releases에 업로드** → 사용자에게 releases 링크 안내. (이 저장소는 공개라 무료.)
- 서명: 개인 사이드로딩 용도. 업데이트 시 동일 키가 필요하므로 **매 빌드 새 debug 키는 금지**. 선택지: ① 키스토어를 GH Secrets에 base64로 (사용자에게 등록 안내 필요) ② 공개 저장소에 키스토어 커밋(제3자가 같은 키로 서명 가능하다는 위험 고지 후 사용자 동의 시 — 개인용이므로 저위험). 다음 세션에서 사용자와 ①/② 결정.
- 사용자 설치 안내문(비개발자용, 「출처를 알 수 없는 앱」 허용 단계 포함)을 반드시 함께 작성.

### 완료 기준
- [ ] 기존 웹 테스트 52개 통과 유지 (웹 회귀 없음)
- [ ] APK: 권한 승인 → 전체 갤러리 자동 로드 → 폴더 만들기 → 갤러리에 실제 앨범 생성 확인
- [ ] 정리함 → 삭제 → 갤러리에서 실제 삭제 확인 (시스템 확인창 경유)
- [ ] Releases에 APK + 설치 안내문, 사용자에게 링크 전달

## 6. 하지 말 것

- 사용자 주소(github.io)와 아티팩트 URL을 바꾸거나 깨뜨리지 말 것.
- IndexedDB 스키마( db명 `photo-organizer`, 키 `이름|크기|수정시각` )를 호환성 없이 바꾸지 말 것 — 사용자의 정리 기록이 이미 들어 있음.
- 테스트 없이 배포하지 말 것. "flake"라고 넘기지 말 것 — 지금까지 전부 실제 버그였음.
- 사용자에게 영어·전문용어·긴 설명 금지. 단계 번호 + 버튼 이름.
