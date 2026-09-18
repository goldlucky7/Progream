# 개발용 테스트 (자동 검사 52개)

```bash
cd photo_organizer
python3 -m pip -q install pillow piexif
python3 dev/make_testpics.py
(python3 -m http.server 8901 &)
export NODE_PATH=/opt/node22/lib/node_modules   # 전역 playwright
node dev/test.js
```
`=== FAIL (0) === / === JS ERRORS (0) ===` 이어야 배포 가능.
자세한 맥락은 ../HANDOVER.md 참고.
