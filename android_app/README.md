# 사진 정리 도우미 — 안드로이드 앱 (개발 메모)

`photo_organizer/index.html`(웹앱)을 WebView로 감싼 설치형 앱. 웹앱이 유일한 UI 소스이고,
빌드 때 `copyWebApp` 태스크가 `photo_organizer/`에서 자동으로 복사해 온다 (이 폴더에 웹 코드 사본 없음).

## 구조

- `app/src/main/java/.../MainActivity.kt` — 전부 여기 있음 (한 파일)
  - WebViewAssetLoader: `/assets/`(웹앱) · `/thumb/{i|v}/{id}`(MediaStore 썸네일 JPEG) · `/media/{i|v}/{id}`(원본 스트리밍)
  - `window.AndroidNative` 브리지: `getInfo()`(동기) / `call(id, method, paramsJson)`(비동기 → `window.__anDone`, 진행률 `window.__anProg`)
  - 메서드: `access`/`request`(권한) · `list`(갤러리 전체) · `album`(Pictures/<이름> 복사, 중복 건너뜀) ·
    `delete`(**createTrashRequest** — 시스템 확인창 1번, 휴지통 30일) · `saveText`(다운로드 폴더) · `open`(다른 앱으로 열기) · `settings`(앱 설정)
- 웹 쪽 대응 코드: `photo_organizer/index.html`의 "네이티브 브리지" 구획 (`window.NativeBridge` 존재로 분기)
- 왜 Capacitor가 아니라 순수 WebView인가: 필요한 네이티브 호출이 위 몇 개뿐이라
  npm·플러그인 체계 없이 CI가 단순·안정적이고 APK도 작다. 기능상 손해 없음.

## 빌드

- 로컬: `cd android_app && ./gradlew assembleRelease` (JDK 17 + Android SDK 필요.
  Claude 원격 컨테이너에서는 dl.google.com이 막혀 있어 **로컬 빌드 불가 — CI에서 빌드**)
- CI: `.github/workflows/android-apk.yml` — `android_app/**` 또는 `photo_organizer/index.html` 푸시 시
  자동 빌드 → Releases의 `apk` 태그에 `PhotoOrganizer.apk` 업로드 (항상 최신 1개)
- 고정 다운로드 주소: `https://github.com/goldlucky7/Progream/releases/latest/download/PhotoOrganizer.apk`
- versionCode = GitHub run number (자동 증가 — 업데이트 설치 보장). 로컬 빌드는 1/"1.0-dev".

## 서명 (중요)

- `signing/photo-organizer.p12` (PKCS12, 별칭 `photoorg`, 비밀번호 `photo-organizer-2026`) 를 **저장소에 커밋**해 둠.
  개인 사이드로딩용이라 이렇게 했고(HANDOVER의 선택지 ②), 공개 저장소라 **누구나 같은 키로 서명할 수 있음**을 사용자에게 고지함.
  이 키를 다른 용도로 재사용하지 말 것.
- **업데이트가 기존 설치 위에 설치되려면 반드시 같은 키**여야 하므로 이 파일을 지우거나 바꾸면 안 됨.
  (바꾸면 사용자는 앱을 지우고 다시 설치해야 하고, 정리 기록도 사라짐)

## 사양 메모

- minSdk 30 (Android 11+) — createTrashRequest·RELATIVE_PATH가 30+, 갤럭시 2019년 이후 커버
- targetSdk 34 — Android 14 "일부 사진만 허용"은 배너로 안내 (index.html `#natPartial`)
- 인터넷 권한 없음 (사진 유출 원천 차단이 셀링 포인트)
- 삭제는 완전삭제가 아니라 **휴지통 이동**(createTrashRequest): 갤러리 앱과 같은 동작이라
  비개발자 사용자에게 안전. 완전삭제로 바꾸려면 MainActivity의 `createTrashRequest` → `createDeleteRequest`.

## 테스트

- `photo_organizer/dev/test.js` 하나로 웹 52개 + 네이티브(모의 AndroidNative) 32개 = **84개 전부 통과해야 배포**.
  네이티브 모의 객체는 test.js 안에 있고 브리지 규약이 바뀌면 같이 바꿔야 한다.
