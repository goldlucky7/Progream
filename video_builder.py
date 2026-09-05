# -*- coding: utf-8 -*-
"""
제미나이 TTS + 캡컷 자동배치 프로그램

프로젝트 폴더(대본.txt + 06_scene-mapping.txt + images/)를 넣으면:
  1. 대본을 씬별로 나누고
  2. 씬마다 제미나이 TTS로 일본어 나레이션을 생성하고 (목소리는 실행 시 선택)
  3. 씬별 오디오 길이에 맞춰 자막(srt)과 타임라인(csv)을 만들고
  4. 캡컷(CapCut) 초안을 자동 생성해서 이미지·오디오·자막을 타임라인에 깔아 줍니다.
     → 캡컷을 열면 초안 목록에 나타나고, 확인 후 내보내기만 하면 됩니다.

사용법: 자동배치.bat 더블클릭 (또는 python video_builder.py "프로젝트폴더")
중간에 끊겨도 다시 실행하면 이미 만든 씬 오디오는 건너뛰고 이어서 합니다.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "builder_config.json"
KEY_FILE = HERE / "api_key.txt"

MODELS = ["gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]

# (이름, 한글 설명) - 위쪽 6개가 시니어 나레이션 추천
VOICES = [
    ("Charon", "남성 느낌 · 낮고 차분한 정보 전달형 (뉴스톤) ★추천"),
    ("Gacrux", "성숙함 · 연륜 있는 목소리 (시니어 채널) ★추천"),
    ("Iapetus", "남성 느낌 · 맑고 또렷함 ★추천"),
    ("Kore", "여성 느낌 · 단단하고 또렷함 ★추천"),
    ("Sulafat", "여성 느낌 · 따뜻함 ★추천"),
    ("Vindemiatrix", "여성 느낌 · 부드럽고 온화함 ★추천"),
    ("Zephyr", "밝음"), ("Puck", "경쾌함"), ("Fenrir", "활기참"),
    ("Leda", "젊은 느낌"), ("Orus", "단호함"), ("Aoede", "산뜻함"),
    ("Callirrhoe", "느긋함"), ("Autonoe", "밝음"), ("Enceladus", "숨결 섞인 부드러움"),
    ("Umbriel", "편안함"), ("Algieba", "매끄러움"), ("Despina", "매끄러움"),
    ("Erinome", "깔끔함"), ("Algenib", "걸걸한 중저음"), ("Rasalgethi", "정보 전달형"),
    ("Laomedeia", "경쾌함"), ("Achernar", "부드러움"), ("Alnilam", "단단함"),
    ("Schedar", "고른 톤"), ("Pulcherrima", "시원시원함"), ("Achird", "친근함"),
    ("Zubenelgenubi", "캐주얼"), ("Sadachbia", "생기 있음"),
    ("Sadaltager", "박식한 느낌"),
]

SPEEDS = [
    ("느리게",  "ゆっくりと、落ち着いた語り口で読んでください。", "시니어 시청자 추천"),
    ("보통",    "自然な速さで、落ち着いて読んでください。", ""),
    ("빠르게",  "ややテンポよく、はきはきと読んでください。", ""),
]

SUB_MAX_CHARS = 38        # 자막 한 개 최대 글자수 (캡컷에서 2줄 이내로 감싸짐)
SCENE_CHUNK_MAX = 3500    # TTS 1회 호출 최대 글자수 (넘으면 문장 단위로 나눠 호출)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

# 캡컷 초안 폴더의 흔한 위치 (Windows)
CAPCUT_DRAFT_CANDIDATES = [
    r"%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft",
    r"%APPDATA%\CapCut\User Data\Projects\com.lveditor.draft",
]


# ── 설정/키 ──────────────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def load_api_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8-sig").strip()
        if key:
            return key
    print("제미나이 API 키가 등록되어 있지 않습니다.")
    print("(https://aistudio.google.com/api-keys 에서 발급)")
    key = input("API 키(AIza...)를 붙여넣고 Enter: ").strip()
    if key:
        KEY_FILE.write_text(key, encoding="utf-8")
        print(f"키를 {KEY_FILE.name} 에 저장했습니다. (절대 공유 금지)")
    return key or None


# ── 대본 씬 분할 ────────────────────────────────────────────────────────────
def read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp932", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def normalize(s):
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"[\s、。「」『』・,.!?！?？…―ー\-()（）\"']", "", s)


def parse_mapping(text):
    entries = []
    for ln in text.splitlines():
        m = re.match(r"^\s*(?:씬|シーン|scene)?\s*0*(\d+)\s*[.:：)\]]\s*(.+)$",
                     ln.strip(), re.I)
        if m:
            entries.append((int(m.group(1)), m.group(2).strip()))
    return entries


def split_scenes(script_text, mapping_entries):
    """씬 매핑의 시작 문구 위치로 대본을 씬별 텍스트로 나눈다."""
    # 정규화 문자열과 원본 위치의 대응표를 만든다
    norm_chars, pos_map = [], []
    for i, ch in enumerate(script_text):
        n = normalize(ch)
        for nc in n:
            norm_chars.append(nc)
            pos_map.append(i)
    norm_script = "".join(norm_chars)

    positions = []
    prev = 0
    problems = []
    for n, phrase in mapping_entries:
        key = normalize(phrase)[:20]
        if len(key) < 4:
            problems.append(f"씬 {n}: 시작 문구가 너무 짧습니다 ({phrase[:30]})")
            continue
        pos = norm_script.find(key, prev)
        if pos < 0:
            pos = norm_script.find(key)
        if pos < 0:
            problems.append(f"씬 {n}: 대본에서 시작 문구를 찾을 수 없습니다 ({phrase[:30]})")
            continue
        positions.append((n, pos_map[pos]))
        prev = pos
    if problems:
        return None, problems

    scenes = []
    for i, (n, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(script_text)
        body = script_text[start:end].strip()
        scenes.append((n, body))
    return scenes, []


def clean_for_tts(text):
    """TTS에 넣기 전 지시문·마크다운 줄 제거"""
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^[\(（\[【].*[\)）\]】]$", s):
            continue
        if re.match(r"^(#{1,6}\s|-{3,}$|```)", s):
            continue
        out.append(s)
    return "\n".join(out)


def split_sentences(text):
    parts = re.split(r"(?<=[。！？!?])", text.replace("\n", ""))
    return [p.strip() for p in parts if p.strip()]


# ── 제미나이 TTS ─────────────────────────────────────────────────────────────
def _tts_request(api_key, model, body):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    part = data["candidates"][0]["content"]["parts"][0]
    inline = part.get("inlineData") or part.get("inline_data")
    audio = base64.b64decode(inline["data"])
    mime = inline.get("mimeType") or inline.get("mime_type") or ""
    m = re.search(r"rate=(\d+)", mime)
    return audio, (int(m.group(1)) if m else 24000)


def make_body(text, voice, speakers=None):
    speech = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    if speakers:  # 2인 대화: [(라벨, 목소리), ...]
        speech = {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
            {"speaker": lb, "voiceConfig":
                {"prebuiltVoiceConfig": {"voiceName": v}}}
            for lb, v in speakers]}}
    return {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": speech}}


def tts_with_retry(api_key, text, voice, speakers=None):
    """PCM 바이트와 샘플레이트 반환. 429는 기다렸다 재시도, 404는 다음 모델."""
    last_err = None
    for model in MODELS:
        for attempt in range(4):
            try:
                return _tts_request(api_key, model, make_body(text, voice, speakers))
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code == 429:
                    wait = 20 * (attempt + 1)
                    print(f"    (사용량 제한 - {wait}초 기다렸다 다시 시도합니다)")
                    time.sleep(wait)
                    continue
                if e.code == 404:
                    break  # 다음 모델로
                if e.code in (401, 403):
                    raise RuntimeError(
                        "API 키가 잘못되었거나 권한이 없습니다. api_key.txt를 확인해 주세요.")
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                if speakers and e.code == 400:
                    raise ValueError("multi-speaker-unsupported: " + detail)
                raise RuntimeError(f"TTS 호출 실패 (HTTP {e.code}): {detail}")
            except Exception as e:
                last_err = e
                time.sleep(5)
    raise RuntimeError(f"TTS 호출이 계속 실패합니다: {last_err}")


def save_wav(path, pcm, rate):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def concat_wavs(paths, out_path):
    with wave.open(str(paths[0]), "rb") as w0:
        params = w0.getparams()
    with wave.open(str(out_path), "wb") as out:
        out.setparams(params)
        for p in paths:
            with wave.open(str(p), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


# ── 자막/타임라인 생성 ──────────────────────────────────────────────────────
def make_cues_for_scene(text, start, duration):
    """씬 텍스트를 자막 조각으로 나누고 글자수 비례로 시간을 배분한다."""
    sentences = split_sentences(re.sub(r"^[^:：\n]{1,8}[:：]\s*", "",
                                       text, flags=re.M))
    pieces = []
    for s in sentences:
        while len(s) > SUB_MAX_CHARS:
            cut = s.rfind("、", 10, SUB_MAX_CHARS)
            if cut < 0:
                cut = SUB_MAX_CHARS
            pieces.append(s[:cut + 1].strip("、") + "、")
            s = s[cut + 1:]
        if s:
            pieces.append(s)
    total_chars = sum(len(p) for p in pieces) or 1
    cues, t = [], start
    for p in pieces:
        d = duration * len(p) / total_chars
        cues.append((t, min(t + d, start + duration), p))
        t += d
    return cues


def wrap_cue(text, max_line=22):
    """긴 자막을 읽기 좋게 2줄로 나눈다 (되도록 、 에서 나눔)."""
    if len(text) <= max_line + 3:
        return text
    mid = len(text) // 2
    cut = text.rfind("、", max(0, mid - 8), min(len(text), mid + 8))
    if cut < 0:
        cut = mid
    else:
        cut += 1
    return text[:cut].rstrip() + "\n" + text[cut:].lstrip()


def srt_timecode(sec):
    ms = int(round((sec - int(sec)) * 1000))
    s = int(sec)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues, path):
    lines = []
    for i, (s, e, txt) in enumerate(cues, start=1):
        lines.append(f"{i}\n{srt_timecode(s)} --> {srt_timecode(e)}\n{wrap_cue(txt)}\n")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


# ── 캡컷 초안 생성 ──────────────────────────────────────────────────────────
def find_capcut_draft_dir(cfg):
    saved = cfg.get("capcut_draft_dir")
    if saved and Path(saved).is_dir():
        return Path(saved)
    for cand in CAPCUT_DRAFT_CANDIDATES:
        p = Path(os.path.expandvars(cand))
        if p.is_dir():
            return p
    return None


def build_capcut_draft(draft_dir, draft_name, scene_files, scene_durs,
                       narration_wav, srt_path):
    import pycapcut as cc
    folder = cc.DraftFolder(str(draft_dir))
    name = draft_name
    n = 2
    while folder.has_draft(name):
        name = f"{draft_name}_{n}"
        n += 1
    script = folder.create_draft(name, 1920, 1080, fps=30)
    script.add_track(cc.TrackType.video, "이미지")
    script.add_track(cc.TrackType.audio, "나레이션")
    t = 0.0
    for img, dur in zip(scene_files, scene_durs):
        seg = cc.VideoSegment(str(img),
                              cc.trange(f"{t:.6f}s", f"{dur:.6f}s"))
        script.add_segment(seg, "이미지")
        t += dur
    total = sum(scene_durs)
    script.add_segment(
        cc.AudioSegment(str(narration_wav), cc.trange("0s", f"{total:.6f}s")),
        "나레이션")
    script.import_srt(str(srt_path), "자막")
    script.save()
    return name


# ── 메뉴 ─────────────────────────────────────────────────────────────────────
def choose_voice(cfg, prompt="어떤 목소리로 만들까요?", key="voice"):
    last = cfg.get(key)
    print()
    print(prompt)
    for i, (name, desc) in enumerate(VOICES, start=1):
        mark = " ←지난번" if name == last else ""
        print(f"  {i:2d}. {name:<14} {desc}{mark}")
    while True:
        raw = input(f"번호 입력 (그냥 Enter = {'지난번 목소리 ' + last if last else '1번'}): ").strip()
        if not raw:
            return last or VOICES[0][0]
        if raw.isdigit() and 1 <= int(raw) <= len(VOICES):
            return VOICES[int(raw) - 1][0]
        match = [n for n, _ in VOICES if n.lower() == raw.lower()]
        if match:
            return match[0]
        print("  1 ~ 30 사이 번호를 입력해 주세요.")


def choose_speed(cfg):
    last = cfg.get("speed", "느리게")
    print()
    print("말하는 속도는요?")
    for i, (name, _style, note) in enumerate(SPEEDS, start=1):
        mark = " ←지난번" if name == last else ""
        note_s = f" ({note})" if note else ""
        print(f"  {i}. {name}{note_s}{mark}")
    raw = input(f"번호 입력 (그냥 Enter = {last}): ").strip()
    if raw.isdigit() and 1 <= int(raw) <= len(SPEEDS):
        return SPEEDS[int(raw) - 1][0]
    return last


def speed_style(name):
    for n, style, _ in SPEEDS:
        if n == name:
            return style
    return SPEEDS[0][1]


def detect_speakers(scene_texts):
    """2인 대화(掛け合い) 대본이면 화자 라벨 2개를 찾는다."""
    counts = {}
    for text in scene_texts:
        for m in re.finditer(r"^\s*([^\s:：]{1,8})\s*[:：]", text, re.M):
            lb = m.group(1)
            counts[lb] = counts.get(lb, 0) + 1
    speakers = [lb for lb, c in sorted(counts.items(), key=lambda x: -x[1])
                if c >= 3]
    return speakers[:2] if len(speakers) >= 2 else []


# ── 메인 ─────────────────────────────────────────────────────────────────────
def run(project_dir, voice_arg=None, speed_arg=None, draft_dir_arg=None):
    """voice_arg/speed_arg를 주면 메뉴 없이 바로 실행된다 (클로드가 대신 실행할 때 사용)."""
    project_dir = Path(project_dir).expanduser()
    if not project_dir.is_dir():
        print(f"폴더를 찾을 수 없습니다: {project_dir}")
        return 2

    # 재료 찾기 (검토 프로그램과 같은 규칙)
    import japan_review as jr
    dummy = jr.Report()
    files = jr.find_project_files(project_dir, dummy)
    if not files["script"]:
        print("대본 파일(파일명에 '대본'이 들어간 .txt)을 찾지 못했습니다.")
        return 1
    images = sorted(files["images"],
                    key=lambda f: (jr.extract_number(f.name) is None,
                                   jr.extract_number(f.name) or 0, f.name))
    if not images:
        print("이미지 파일이 없습니다. images 폴더에 001.png 처럼 넣어 주세요.")
        return 1

    script_text = read_text(files["script"])

    # 씬 나누기: 씬 매핑이 있으면 그것으로, 없으면 빈 줄 기준 문단으로
    if files["mapping"]:
        entries = parse_mapping(read_text(files["mapping"]))
        scenes, problems = split_scenes(script_text, entries)
        if problems:
            print("씬 매핑에 문제가 있어 진행할 수 없습니다:")
            for p in problems[:10]:
                print("  -", p)
            print("review.bat 으로 먼저 검토하고 씬 매핑을 고쳐 주세요.")
            return 1
    else:
        paras = [p.strip() for p in re.split(r"\n\s*\n", script_text) if p.strip()]
        scenes = list(enumerate(paras, start=1))
        print(f"씬 매핑 파일이 없어 빈 줄 기준으로 {len(scenes)}개 문단을 씬으로 사용합니다.")

    if len(scenes) != len(images):
        print(f"씬 수({len(scenes)}개)와 이미지 수({len(images)}장)가 다릅니다.")
        print("씬마다 이미지가 1장씩 필요합니다. review.bat 으로 확인 후 맞춰 주세요.")
        return 1

    scene_texts = [clean_for_tts(t) for _n, t in scenes]

    api_key = load_api_key()
    if not api_key:
        return 1

    cfg = load_config()
    speakers = detect_speakers(scene_texts)
    voice = voice_b = None
    valid_names = {n.lower(): n for n, _ in VOICES}
    if voice_arg:
        if voice_arg.lower() not in valid_names:
            print(f"'{voice_arg}'는 없는 목소리입니다. 가능한 이름: "
                  + ", ".join(n for n, _ in VOICES))
            return 1
        voice = valid_names[voice_arg.lower()]
        if speakers:
            voice_b = cfg.get("voice_b") or voice
            print(f"2인 대화 대본: {speakers[0]}={voice}, {speakers[1]}={voice_b}")
    elif speakers:
        print(f"\n2인 대화 대본으로 보입니다 (화자: {speakers[0]}, {speakers[1]})")
        voice = choose_voice(cfg, f"'{speakers[0]}' 역할 목소리는?", "voice")
        voice_b = choose_voice(cfg, f"'{speakers[1]}' 역할 목소리는?", "voice_b")
    else:
        voice = choose_voice(cfg)
    if speed_arg:
        if speed_arg not in [n for n, _s, _x in SPEEDS]:
            print(f"속도는 {', '.join(n for n, _s, _x in SPEEDS)} 중 하나여야 합니다.")
            return 1
        speed = speed_arg
    else:
        speed = choose_speed(cfg)
    cfg.update({"voice": voice, "speed": speed})
    if voice_b:
        cfg["voice_b"] = voice_b
    save_config(cfg)
    style = speed_style(speed)

    out_dir = project_dir / "출력"
    part_dir = out_dir / "씬오디오"
    part_dir.mkdir(parents=True, exist_ok=True)

    # 씬별 TTS (이미 만든 씬은 건너뜀 = 이어하기)
    print()
    print("=" * 52)
    print(f" 씬 {len(scenes)}개 나레이션 생성 시작 (목소리: {voice}"
          + (f" + {voice_b}" if voice_b else "") + f", 속도: {speed})")
    print("=" * 52)
    wav_paths = []
    for i, text in enumerate(scene_texts, start=1):
        wav_path = part_dir / f"씬{i:03d}.wav"
        wav_paths.append(wav_path)
        if wav_path.exists() and wav_path.stat().st_size > 2000:
            print(f"[{i}/{len(scenes)}] 이미 있음 - 건너뜀 ({wav_path.name})")
            continue
        print(f"[{i}/{len(scenes)}] 생성 중 ({len(text)}자) ... ", end="", flush=True)
        chunks = [text]
        if len(text) > SCENE_CHUNK_MAX:
            chunks, cur = [], ""
            for s in split_sentences(text):
                if len(cur) + len(s) > SCENE_CHUNK_MAX and cur:
                    chunks.append(cur)
                    cur = ""
                cur += s
            if cur:
                chunks.append(cur)
        pcm_all, rate = b"", 24000
        for chunk in chunks:
            sp = ([(speakers[0], voice), (speakers[1], voice_b)]
                  if voice_b and re.search(r"[:：]", chunk) else None)
            try:
                pcm, rate = tts_with_retry(api_key, style + "\n" + chunk,
                                           voice, speakers=sp)
            except ValueError:
                # 2인 대화가 안 되는 모델이면 라벨을 떼고 한 목소리로
                plain = re.sub(r"^\s*[^\s:：]{1,8}\s*[:：]\s*", "",
                               chunk, flags=re.M)
                pcm, rate = tts_with_retry(api_key, style + "\n" + plain, voice)
            pcm_all += pcm
            time.sleep(1.5)
        save_wav(wav_path, pcm_all, rate)
        print(f"완료 ({wav_duration(wav_path):.1f}초)")

    durs = [wav_duration(p) for p in wav_paths]
    total = sum(durs)
    narration = out_dir / "나레이션_전체.wav"
    concat_wavs(wav_paths, narration)
    print(f"\n전체 나레이션: {narration.name} ({int(total // 60)}분 {int(total % 60)}초)")

    # 자막 + 타임라인
    cues, t = [], 0.0
    for text, dur in zip(scene_texts, durs):
        cues.extend(make_cues_for_scene(text, t, dur))
        t += dur
    srt_path = out_dir / "자막.srt"
    write_srt(cues, srt_path)
    timeline_path = out_dir / "타임라인.csv"
    t = 0.0
    rows = ["씬,파일,시작(초),길이(초)"]
    for i, (img, dur) in enumerate(zip(images, durs), start=1):
        rows.append(f"{i},{img.name},{t:.2f},{dur:.2f}")
        t += dur
    timeline_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"자막 {len(cues)}개({srt_path.name}), 타임라인({timeline_path.name}) 생성 완료")

    # 캡컷 초안
    print()
    if draft_dir_arg and Path(draft_dir_arg).is_dir():
        draft_dir = Path(draft_dir_arg)
        cfg["capcut_draft_dir"] = str(draft_dir)
        save_config(cfg)
    else:
        draft_dir = find_capcut_draft_dir(cfg)
    if draft_dir is None and not voice_arg:   # 메뉴 모드에서만 경로를 물어봄
        print("캡컷 초안 폴더를 자동으로 찾지 못했습니다.")
        print("캡컷 → 설정 → '초안 위치'에 나온 경로를 붙여넣어 주세요.")
        raw = input("초안 폴더 경로 (건너뛰려면 그냥 Enter): ").strip().strip('"')
        if raw and Path(raw).is_dir():
            draft_dir = Path(raw)
            cfg["capcut_draft_dir"] = raw
            save_config(cfg)
    if draft_dir is not None:
        try:
            name = build_capcut_draft(
                draft_dir, project_dir.name + "_자동배치",
                images, durs, narration, srt_path)
            print("=" * 52)
            print(f" ✅ 캡컷 초안 생성 완료: {name}")
            print("    캡컷을 열면 초안 목록에 나타납니다. 열어서 확인 후 내보내기 하세요.")
            print("    (이미지·오디오 파일을 옮기거나 지우면 초안에서 깨집니다)")
            print("=" * 52)
        except Exception as e:
            print(f"캡컷 초안 생성에 실패했습니다: {e}")
            print("→ 대신 '출력' 폴더의 나레이션·자막·타임라인을 캡컷에 직접 불러오시면 됩니다.")
            print("→ 이 오류 메시지를 클로드에게 보여주시면 고쳐 드립니다.")
    else:
        print("캡컷 초안 생성은 건너뛰었습니다. '출력' 폴더의 파일을 직접 불러오세요.")

    print(f"\n마지막으로 review.bat 에 이 폴더를 드래그해서 검수하는 것을 추천합니다.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="제미나이 TTS + 캡컷 자동배치")
    parser.add_argument("folder", nargs="?", help="프로젝트 폴더")
    parser.add_argument("--voice", help="목소리 이름 (주면 메뉴 없이 실행, 예: Gacrux)")
    parser.add_argument("--speed", help="속도: 느리게/보통/빠르게")
    parser.add_argument("--draft-dir", help="캡컷 초안 폴더 경로 직접 지정")
    args = parser.parse_args()
    folder = args.folder or input(
        "프로젝트 폴더(대본+씬매핑+이미지) 경로를 붙여넣고 Enter: ").strip().strip('"')
    sys.exit(run(folder, voice_arg=args.voice, speed_arg=args.speed,
                 draft_dir_arg=args.draft_dir))


if __name__ == "__main__":
    main()
