# Claude 신기능 알림 시스템

매일 아침, 클로드(Claude / Claude Code)에 새로 생기거나 잘 안 알려진 기능을
찾아서 **휴대폰 푸시 알림**으로 보내주는 자동화 설정입니다.

## 구성

| 파일 | 용도 |
|---|---|
| `claude-hidden-features.md` | 지금까지 정리된 **숨은 기능 사전** (쉬운 설명 + 사용법) |
| `feature-log.md` | 이미 알림을 보낸 기능 **기록**. 같은 걸 두 번 알리지 않기 위한 용도 |

## 동작 방식

1. 매일 아침 9시(한국시간) 직전에 클로드 세션이 자동으로 실행됩니다.
2. 아래 공식 소스를 확인합니다.
   - Claude Code 주간 다이제스트 — https://code.claude.com/docs/en/whats-new
   - Claude Code 체인지로그 — https://code.claude.com/docs/en/changelog
   - Anthropic 공식 발표 — https://claude.com/blog-category/announcements
3. `feature-log.md`에 없는 **새 항목만** 골라냅니다.
4. 새 항목이 있으면 쉬운 한국어 설명 + 사용법으로 정리해 푸시 알림을 보내고,
   `feature-log.md`와 `claude-hidden-features.md`를 갱신합니다.
5. 새 항목이 없으면 아무 알림도 보내지 않고 조용히 종료합니다.

## 알림 끄기 / 바꾸기

클로드에게 말로 시키면 됩니다.

- 끄기: "신기능 알림 루틴 삭제해줘"
- 주기 변경: "신기능 알림 주 1회로 바꿔줘"
- 잠시 멈춤: "신기능 알림 잠깐 꺼줘"

또는 웹에서 직접: **claude.ai/code → Routines**
