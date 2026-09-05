# -*- coding: utf-8 -*-
"""
제미나이 TTS 목소리 테스트 프로그램

api_key.txt 에 저장된 제미나이 API 키로, 같은 일본어 문장을
여러 목소리로 만들어 '목소리샘플' 폴더에 wav 파일로 저장해 줍니다.
들어보고 마음에 드는 목소리를 고르면 됩니다.

사용법: tts_test.bat 더블클릭 (또는 python tts_test.py)
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).parent
KEY_FILE = HERE / "api_key.txt"
OUT_DIR = HERE / "목소리샘플"

# 시도할 모델 순서 - 앞의 것이 안 되면 다음 것으로 자동 전환
MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
]

# 테스트할 목소리들 (이름, 한글 설명)
VOICES = [
    ("Charon", "남성 느낌 · 낮고 차분한 정보 전달형 (뉴스톤)"),
    ("Gacrux", "성숙한 느낌 · 연륜 있는 목소리 (시니어 채널에 어울림)"),
    ("Iapetus", "남성 느낌 · 맑고 또렷함"),
    ("Kore", "여성 느낌 · 단단하고 또렷함"),
    ("Sulafat", "여성 느낌 · 따뜻함"),
    ("Vindemiatrix", "여성 느낌 · 부드럽고 온화함"),
]

# 목소리에게 주는 지시 + 읽을 일본어 샘플 문장
STYLE = "落ち着いた、ゆっくりとした語り口で読んでください。"
SAMPLE_TEXT = (
    "皆さん、こんにちは。今日は、日本経済の大きな転換点についてお話しします。"
    "銀行に眠っていたお金が、いま静かに動き始めています。"
    "最後まで、ごゆっくりお楽しみください。"
)


def load_api_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8-sig").strip()
        if key:
            return key
    print("=" * 52)
    print(" 제미나이 API 키가 아직 등록되지 않았습니다.")
    print(" (https://aistudio.google.com/api-keys 에서 발급)")
    print("=" * 52)
    key = input("발급받은 API 키(AIza...로 시작)를 붙여넣고 Enter: ").strip()
    if not key:
        return None
    KEY_FILE.write_text(key, encoding="utf-8")
    print(f"키를 {KEY_FILE.name} 에 저장했습니다. 다음부터는 바로 실행됩니다.")
    print("(이 파일은 절대 다른 사람에게 보내거나 인터넷에 올리지 마세요)")
    return key


def synthesize(api_key, model, voice, text):
    """제미나이 TTS 호출 → PCM(24kHz 16bit mono) 바이트 반환"""
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice}
                }
            },
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    part = data["candidates"][0]["content"]["parts"][0]
    inline = part.get("inlineData") or part.get("inline_data")
    audio = base64.b64decode(inline["data"])
    mime = inline.get("mimeType") or inline.get("mime_type") or ""
    m = re.search(r"rate=(\d+)", mime)
    rate = int(m.group(1)) if m else 24000
    return audio, rate


def save_wav(path, pcm, rate):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def explain_error(e):
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = ""
        if e.code in (401, 403):
            return ("API 키가 잘못되었거나 권한이 없습니다. "
                    "api_key.txt 의 키를 다시 확인해 주세요.", detail, False)
        if e.code == 429:
            return ("오늘의 무료 사용 한도를 다 썼거나 너무 빨리 요청했습니다. "
                    "잠시 뒤 다시 시도하거나, 결제 연결(종량제)을 하면 해결됩니다.",
                    detail, False)
        if e.code == 404:
            return ("이 모델을 사용할 수 없습니다. 다음 모델로 다시 시도합니다.",
                    detail, True)  # True = 다른 모델로 재시도
        if e.code == 400:
            return ("요청 형식 오류입니다. 아래 상세 내용을 복사해서 알려주세요.",
                    detail, True)
        return (f"HTTP {e.code} 오류가 났습니다.", detail, False)
    return (f"연결에 실패했습니다: {e}\n인터넷 연결을 확인해 주세요.", "", False)


def main():
    api_key = load_api_key()
    if not api_key:
        print("키가 입력되지 않아 종료합니다.")
        return 1

    OUT_DIR.mkdir(exist_ok=True)
    print()
    print("=" * 52)
    print(" 같은 일본어 문장을 여러 목소리로 만들어 봅니다.")
    print(f" 결과 폴더: {OUT_DIR}")
    print("=" * 52)

    full_text = STYLE + "\n" + SAMPLE_TEXT
    model_idx = 0
    ok = 0
    for i, (voice, desc) in enumerate(VOICES, start=1):
        made = False
        while model_idx < len(MODELS):
            model = MODELS[model_idx]
            print(f"[{i}/{len(VOICES)}] {voice} ({desc}) ... ", end="", flush=True)
            try:
                pcm, rate = synthesize(api_key, model, voice, full_text)
                out = OUT_DIR / f"{i:02d}_{voice}.wav"
                save_wav(out, pcm, rate)
                print(f"완료 → {out.name}")
                ok += 1
                made = True
                break
            except Exception as e:
                msg, detail, try_next_model = explain_error(e)
                print("실패")
                print(f"    → {msg}")
                if detail:
                    print(f"    상세: {detail[:200]}")
                if try_next_model and model_idx < len(MODELS) - 1:
                    model_idx += 1
                    print(f"    → 모델을 {MODELS[model_idx]} 로 바꿔서 재시도합니다.")
                    continue
                if not try_next_model and "한도" not in msg:
                    return 1  # 키 문제 등은 더 시도해도 소용없음
                break
        if not made and model_idx >= len(MODELS):
            break
        time.sleep(2)  # 무료 등급 속도 제한 배려

    print()
    print("-" * 52)
    if ok:
        print(f" 샘플 {ok}개 완성! '{OUT_DIR.name}' 폴더를 열어서 하나씩 들어보세요.")
        print(" 마음에 드는 목소리 이름(파일명에 있음)을 기억해 두시면,")
        print(" 나중에 본편 프로그램 만들 때 그 목소리로 설정해 드립니다.")
        try:
            if os.name == "nt":
                os.startfile(OUT_DIR)  # noqa
        except Exception:
            pass
    else:
        print(" 샘플을 만들지 못했습니다. 위의 오류 메시지를 확인해 주세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
