# -*- coding: utf-8 -*-
"""
일본 영상 검토 프로그램 (Vrew용)

완성(또는 편집 중인) 일본어 유튜브 영상을 자동으로 검토합니다.

검토 폴더 하나에 아래 파일들을 넣고 실행하면:
  - 영상 파일        : .mp4 / .mov / .mkv / .avi
  - 이미지 폴더/파일  : 영상에 쓴 씬 이미지들 (파일명에 씬 번호가 있으면 순서 검사)
  - 대본             : 파일명에 "대본"이 들어간 .txt
  - 자막             : Vrew에서 내보낸 .srt (파일 > 다른 형식으로 내보내기 > 자막파일 SRT)
  - 매칭표           : 파일명에 "매칭" 또는 "씬"이 들어간 .txt/.csv/.xlsx (씬번호 + 그 씬의 대본 시작 문구)

이렇게 검사합니다:
  1. 자막 <-> 대본 대조     : 빠진 문장, 달라진 문장, 순서 뒤바뀜
  2. 이미지 <-> 영상 매칭    : 안 쓰인 이미지, 씬 순서 어긋남, 등장 타이밍 어긋남
  3. 자막 위치 점검          : 자막 위치가 들쭉날쭉한 구간 (OCR 설치 시 자동, 미설치 시 눈으로 확인용 타임라인 제공)
  4. 일본어 자연스러움 검토   : 번역투/어색한 표현을 Claude가 원어민 편집자 관점으로 검토
                              (API 키가 있으면 자동, 없으면 Claude에 붙여넣을 검토요청 파일 생성)

사용법:
  python jp_review.py "검토폴더 경로"
  python jp_review.py "검토폴더 경로" --no-ai   (자연스러움 AI 검토 건너뛰기)

결과: 검토폴더 안에 "검토보고서.html" 생성
"""

import base64
import datetime
import io
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import cv2
    import numpy as np
    from PIL import Image
except ImportError:
    print("필요한 라이브러리가 없습니다. install.bat 을 다시 실행해 주세요.")
    print("  python -m pip install -r requirements.txt")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

CLAUDE_MODEL = "claude-opus-5"

# ---------------------------------------------------------------- 파일 찾기


def read_text_any_encoding(path):
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp949", "shift_jis"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def find_materials(folder):
    folder = Path(folder)
    mats = {"video": None, "images": [], "script": None, "srt": None, "mapping": None}

    all_files = [p for p in folder.rglob("*") if p.is_file()]
    for p in all_files:
        ext = p.suffix.lower()
        name = p.name
        if ext in VIDEO_EXTS and mats["video"] is None:
            mats["video"] = p
        elif ext in IMAGE_EXTS:
            mats["images"].append(p)
        elif ext == ".srt" and mats["srt"] is None:
            mats["srt"] = p
        elif ext in (".txt", ".csv", ".xlsx"):
            if any(k in name for k in ("매칭", "매핑", "mapping", "scene", "씬")) and mats["mapping"] is None:
                mats["mapping"] = p
            elif ext == ".txt" and any(k in name for k in ("대본", "script", "台本")) and mats["script"] is None:
                mats["script"] = p

    # 대본을 못 찾았으면: 매칭표/자막이 아닌 txt 중 가장 큰 파일을 대본으로 간주
    if mats["script"] is None:
        candidates = [
            p for p in all_files
            if p.suffix.lower() == ".txt" and p != mats["mapping"]
        ]
        if candidates:
            mats["script"] = max(candidates, key=lambda p: p.stat().st_size)

    mats["images"].sort(key=lambda p: natural_key(p.name))
    return mats


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def scene_number_from_name(name):
    m = re.search(r"(\d+)", Path(name).stem)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- SRT / 텍스트


def parse_srt(text):
    """[(start_sec, end_sec, text), ...]"""
    cues = []
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    time_re = re.compile(
        r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
    )
    for block in blocks:
        lines = [l for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        m = None
        idx = 0
        for i, line in enumerate(lines):
            m = time_re.search(line)
            if m:
                idx = i
                break
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        body = " ".join(lines[idx + 1:]).strip()
        if body:
            cues.append((start, end, body))
    cues.sort(key=lambda c: c[0])
    return cues


def normalize_ja(text):
    """대조용 정규화: 공백/구두점/기호 제거"""
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"[、。，．・「」『』（）()【】\[\]!?！？…‥〜~―—:：;；\"']", "", text)
    return text


def fmt_time(sec):
    sec = int(round(sec))
    return "%d:%02d:%02d" % (sec // 3600, (sec % 3600) // 60, sec % 60)


def check_subtitles_vs_script(cues, script_text):
    """자막(SRT) <-> 대본 대조. issues 리스트 반환"""
    import difflib

    issues = []
    norm_script = normalize_ja(script_text)
    positions = []  # 각 자막이 대본에서 발견된 위치

    search_from = 0
    for (start, end, body) in cues:
        norm_cue = normalize_ja(body)
        if len(norm_cue) < 2:
            positions.append(None)
            continue
        # 1) 정확 매치 (직전 위치 이후 우선, 없으면 전체에서)
        pos = norm_script.find(norm_cue, max(0, search_from - 20))
        if pos < 0:
            pos = norm_script.find(norm_cue)
        if pos >= 0:
            positions.append(pos)
            search_from = pos + len(norm_cue)
            continue
        # 2) 유사 매치: 대본에서 가장 비슷한 구간 탐색
        best_ratio, best_pos = 0.0, -1
        window = len(norm_cue)
        step = max(1, window // 3)
        for i in range(0, max(1, len(norm_script) - window + 1), step):
            r = difflib.SequenceMatcher(None, norm_cue, norm_script[i:i + window]).ratio()
            if r > best_ratio:
                best_ratio, best_pos = r, i
        if best_ratio >= 0.7:
            issues.append({
                "level": "warn",
                "check": "자막-대본 대조",
                "time": fmt_time(start),
                "msg": "자막이 대본과 조금 다릅니다 (유사도 %d%%)" % int(best_ratio * 100),
                "detail": "자막: %s" % body,
            })
            positions.append(best_pos)
            search_from = best_pos + window
        else:
            issues.append({
                "level": "error",
                "check": "자막-대본 대조",
                "time": fmt_time(start),
                "msg": "이 자막을 대본에서 찾을 수 없습니다 (오타이거나 대본에 없는 문장)",
                "detail": "자막: %s" % body,
            })
            positions.append(None)

    # 순서 검사
    prev = -1
    for (cue, pos) in zip(cues, positions):
        if pos is None:
            continue
        if pos < prev - 30:  # 확실히 앞으로 되돌아간 경우만
            issues.append({
                "level": "error",
                "check": "자막-대본 대조",
                "time": fmt_time(cue[0]),
                "msg": "자막 순서가 대본 순서와 뒤바뀐 것 같습니다",
                "detail": "자막: %s" % cue[2],
            })
        prev = max(prev, pos if pos is not None else prev)

    # 대본에서 자막으로 안 만들어진(빠진) 구간 검사
    covered = np.zeros(len(norm_script) + 1, dtype=bool)
    for (cue, pos) in zip(cues, positions):
        if pos is None:
            continue
        ln = len(normalize_ja(cue[2]))
        covered[pos:pos + ln] = True
    # 30자 이상 연속으로 자막에 안 나온 대본 구간 찾기
    run_start = None
    for i in range(len(norm_script) + 1):
        is_cov = covered[i] if i < len(norm_script) else True
        if not is_cov and run_start is None:
            run_start = i
        elif is_cov and run_start is not None:
            if i - run_start >= 30:
                snippet = norm_script[run_start:min(i, run_start + 60)]
                issues.append({
                    "level": "error",
                    "check": "자막-대본 대조",
                    "time": "-",
                    "msg": "대본의 이 부분(약 %d자)이 자막에 없습니다 (누락 의심)" % (i - run_start),
                    "detail": "대본: %s..." % snippet,
                })
            run_start = None
    return issues


# ---------------------------------------------------------------- 영상/이미지


def dhash_img(pil_img, size=8):
    g = pil_img.convert("L").resize((size + 1, size), Image.LANCZOS)
    arr = np.asarray(g, dtype=np.int16)
    return (arr[:, 1:] > arr[:, :-1]).flatten()


def hist_sig(pil_img):
    arr = np.asarray(pil_img.convert("RGB").resize((64, 64)))
    hists = [np.histogram(arr[:, :, c], bins=16, range=(0, 256))[0] for c in range(3)]
    v = np.concatenate(hists).astype(float)
    s = v.sum()
    return v / s if s else v


def hist_corr(a, b):
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def sample_video_frames(video_path, interval_sec=1.0, thumb_every=0):
    """[(t, dhash, hist, thumb_b64_or_None), ...]"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return [], 0.0
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if fps <= 0:
        fps = 30.0
    step = max(1, int(round(fps * interval_sec)))
    frames = []
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                t = idx / fps
                pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                thumb = None
                if thumb_every and (len(frames) % thumb_every == 0):
                    thumb = thumb_b64(pil)
                frames.append((t, dhash_img(pil), hist_sig(pil), thumb))
        idx += 1
    duration = idx / fps
    cap.release()
    return frames, duration


def thumb_b64(pil_img, width=320):
    w, h = pil_img.size
    img = pil_img.resize((width, max(1, int(h * width / w))))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def match_images_in_video(images, frames):
    """이미지별 등장 시각 목록. {path: [t, ...]}"""
    result = {}
    for img_path in images:
        try:
            pil = Image.open(img_path)
            ih = dhash_img(pil)
            hh = hist_sig(pil)
        except Exception:
            result[img_path] = []
            continue
        times = []
        for (t, fh, fhist, _thumb) in frames:
            d = int(np.count_nonzero(ih != fh))
            if d <= 14 or (d <= 22 and hist_corr(hh, fhist) >= 0.97):
                times.append(t)
        result[img_path] = times
    return result


def parse_mapping(path, script_text):
    """매칭표에서 (씬번호, 대본 시작 문구) 목록 추출. 형식이 달라도 최대한 관대하게."""
    rows = []
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    rows.append(" | ".join(cells))
            wb.close()
        except Exception:
            return []
    else:
        rows = [l for l in read_text_any_encoding(path).splitlines() if l.strip()]

    norm_script = normalize_ja(script_text)
    mapping = []
    for line in rows:
        m = re.search(r"(\d+)", line)
        if not m:
            continue
        scene_no = int(m.group(1))
        # 숫자 이후 부분에서 대본에 실제로 존재하는 가장 긴 문구 조각을 찾는다
        rest = line[m.end():]
        chunks = [normalize_ja(c) for c in re.split(r"[|,\t:：>-]+", rest)]
        chunks = [c for c in chunks if len(c) >= 4]
        best = None
        for c in sorted(chunks, key=len, reverse=True):
            probe = c[:20]
            pos = norm_script.find(probe)
            if pos >= 0:
                best = (pos, probe)
                break
        if best:
            mapping.append({"scene": scene_no, "script_pos": best[0], "snippet": best[1]})
    mapping.sort(key=lambda r: r["scene"])
    return mapping


def expected_scene_times(mapping, cues):
    """매칭표의 씬 시작 문구 -> 자막 타이밍으로 씬 시작 시각 추정"""
    cue_norms = [(c[0], normalize_ja(c[2])) for c in cues]
    for row in mapping:
        row["expected_time"] = None
        probe = row["snippet"][:12]
        for (start, norm) in cue_norms:
            if probe and probe in norm:
                row["expected_time"] = start
                break
        if row["expected_time"] is None and len(probe) >= 6:
            for (start, norm) in cue_norms:
                if probe[:6] in norm:
                    row["expected_time"] = start
                    break
    return mapping


def check_images(images, frames, mapping, cues, duration):
    issues = []
    appear = match_images_in_video(images, frames)

    first_times = {}
    for img_path, times in appear.items():
        if not times:
            issues.append({
                "level": "error",
                "check": "이미지-영상 매칭",
                "time": "-",
                "msg": "이 이미지가 영상에서 발견되지 않았습니다 (누락 또는 크게 변형됨)",
                "detail": img_path.name,
            })
        else:
            first_times[img_path] = min(times)

    # 씬 번호 순서 vs 영상 등장 순서
    numbered = [(scene_number_from_name(p.name), p) for p in first_times]
    numbered = [(n, p) for (n, p) in numbered if n is not None]
    numbered.sort(key=lambda x: x[0])
    prev_t, prev_n, prev_p = -1.0, None, None
    for (n, p) in numbered:
        t = first_times[p]
        if t < prev_t - 2.0:
            issues.append({
                "level": "error",
                "check": "이미지-영상 매칭",
                "time": fmt_time(t),
                "msg": "씬 순서가 뒤바뀌었습니다: 씬%d(%s)는 씬%d(%s) 뒤에 나와야 하는데 영상에서는 더 먼저 등장합니다"
                       % (n, p.name, prev_n if prev_n is not None else 0, prev_p.name if prev_p else "?"),
                "detail": "씬%s(%s) 첫 등장 %s / 씬%d(%s) 첫 등장 %s"
                          % (prev_n, prev_p.name if prev_p else "?", fmt_time(prev_t), n, p.name, fmt_time(t)),
            })
        if t > prev_t:
            prev_t, prev_n, prev_p = t, n, p

    # 매칭표 기대 시각 vs 실제 등장 시각
    if mapping:
        scene_to_img = {}
        for p in first_times:
            n = scene_number_from_name(p.name)
            if n is not None and n not in scene_to_img:
                scene_to_img[n] = p
        for row in mapping:
            exp = row.get("expected_time")
            img = scene_to_img.get(row["scene"])
            if exp is None or img is None:
                continue
            actual = first_times[img]
            if abs(actual - exp) > 10.0:
                issues.append({
                    "level": "warn",
                    "check": "이미지-영상 매칭",
                    "time": fmt_time(actual),
                    "msg": "씬%d 이미지(%s)의 등장 시점이 매칭표 기준과 %d초 어긋납니다"
                           % (row["scene"], img.name, int(abs(actual - exp))),
                    "detail": "매칭표 기준 약 %s / 실제 첫 등장 %s" % (fmt_time(exp), fmt_time(actual)),
                })
    return issues, appear


# ---------------------------------------------------------------- 자막 위치


def check_subtitle_positions(video_path, cues):
    """OCR(tesseract)이 설치된 경우: 자막 위치 일관성 자동 검사"""
    issues = []
    ocr_ok = shutil.which("tesseract") is not None
    if ocr_ok:
        try:
            import pytesseract  # noqa
        except ImportError:
            ocr_ok = False
    if not ocr_ok or not cues:
        return issues, None

    import pytesseract
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return issues, None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    sample_cues = cues[:: max(1, len(cues) // 30)][:30]
    y_centers = []
    per_cue = []
    for (start, end, body) in sample_cues:
        mid = (start + end) / 2.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        h = frame.shape[0]
        try:
            data = pytesseract.image_to_data(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), lang="jpn",
                output_type=pytesseract.Output.DICT,
            )
        except Exception:
            cap.release()
            return issues, None
        ys = [
            data["top"][i] + data["height"][i] / 2.0
            for i in range(len(data["text"]))
            if data["text"][i].strip() and int(data["conf"][i]) > 30
        ]
        if ys:
            yc = float(np.median(ys)) / h
            y_centers.append(yc)
            per_cue.append((start, body, yc))
        else:
            per_cue.append((start, body, None))

    if len(y_centers) >= 5:
        med = float(np.median(y_centers))
        for (start, body, yc) in per_cue:
            if yc is None:
                issues.append({
                    "level": "warn", "check": "자막 위치",
                    "time": fmt_time(start),
                    "msg": "이 자막 구간에서 화면의 글자를 인식하지 못했습니다 (자막 누락 여부 확인)",
                    "detail": body,
                })
            elif abs(yc - med) > 0.10:
                issues.append({
                    "level": "warn", "check": "자막 위치",
                    "time": fmt_time(start),
                    "msg": "자막 위치가 다른 구간과 눈에 띄게 다릅니다 (기준 %d%% 지점, 이 구간 %d%% 지점)"
                           % (int(med * 100), int(yc * 100)),
                    "detail": body,
                })
    cap.release()
    return issues, "OCR 검사 완료 (표본 %d개 구간)" % len(per_cue)


def build_contact_sheet(video_path, cues, count=12):
    """눈으로 확인용: 자막 구간별 썸네일 타임라인"""
    thumbs = []
    if not cues:
        return thumbs
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return thumbs
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    picked = cues[:: max(1, len(cues) // count)][:count]
    for (start, end, body) in picked:
        mid = (start + end) / 2.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(mid * fps))
        ok, frame = cap.read()
        if not ok:
            continue
        pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        thumbs.append({"time": fmt_time(mid), "text": body[:40], "b64": thumb_b64(pil)})
    cap.release()
    return thumbs


# ---------------------------------------------------------------- 일본어 자연스러움 (Claude)

NATURALNESS_SYSTEM = """あなたは日本のテレビ・YouTube業界で20年働いてきたベテランのナレーション原稿編集者です。
50〜70代の日本人視聴者向けYouTubeナレーション原稿をチェックします。

原稿を読んで、日本語ネイティブが読んだ・聞いたときに「外国人が書いた日本語だ」と感じる箇所を全て指摘してください。
特に以下を重点的に:
- 翻訳調(韓国語・英語の直訳のような表現)
- 不自然なコロケーション(単語の組み合わせ)
- 敬体(です・ます)の不統一
- 高齢の視聴者に不自然なカタカナ語・若者言葉
- 日本では使わない言い回し・比喩

반드시 아래 JSON 형식으로만 답하세요. JSON 외의 글자는 출력하지 마세요.
{"score": 1~10 (10=완전한 원어민 수준), "summary_ko": "전체 평가를 한국어 2~3문장으로",
 "issues": [{"original": "문제가 된 일본어 원문", "type": "번역투|어색한 표현|경어 불일치|카타카나 과다|기타",
             "suggestion": "자연스러운 일본어 수정안", "reason_ko": "무엇이 왜 어색한지 한국어 설명"}]}
문제가 없으면 issues는 빈 배열로."""


def find_api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    key_file = BASE_DIR / "api_key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8", errors="replace").strip()
        if key:
            return key
    return None


def split_chunks(text, size=4000):
    chunks = []
    buf = ""
    for para in re.split(r"(\n)", text):
        if len(buf) + len(para) > size and buf:
            chunks.append(buf)
            buf = para
        else:
            buf += para
    if buf.strip():
        chunks.append(buf)
    return chunks


def parse_json_loose(text):
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def check_naturalness(script_text, api_key):
    """Claude API로 일본어 자연스러움 검토. (issues, summaries) 반환"""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    issues = []
    summaries = []
    chunks = split_chunks(script_text)
    print("일본어 자연스러움 검토 중... (%d개 구간, Claude 호출)" % len(chunks))

    for i, chunk in enumerate(chunks, 1):
        print("  구간 %d/%d 검토 중..." % (i, len(chunks)))
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL,
                max_tokens=16000,
                system=NATURALNESS_SYSTEM,
                messages=[{"role": "user", "content": "다음 일본어 원고를 검토해 주세요:\n\n" + chunk}],
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.AuthenticationError:
            issues.append({"level": "error", "check": "일본어 자연스러움", "time": "-",
                           "msg": "API 키가 올바르지 않습니다. api_key.txt 내용을 확인해 주세요.", "detail": ""})
            return issues, summaries
        except anthropic.RateLimitError:
            issues.append({"level": "warn", "check": "일본어 자연스러움", "time": "-",
                           "msg": "API 호출 한도에 걸려 구간 %d부터 검토를 중단했습니다. 잠시 후 다시 실행해 주세요." % i,
                           "detail": ""})
            return issues, summaries
        except anthropic.APIConnectionError:
            issues.append({"level": "warn", "check": "일본어 자연스러움", "time": "-",
                           "msg": "인터넷 연결 문제로 구간 %d부터 검토하지 못했습니다." % i, "detail": ""})
            return issues, summaries
        except anthropic.APIStatusError as e:
            issues.append({"level": "warn", "check": "일본어 자연스러움", "time": "-",
                           "msg": "API 오류(%s)로 구간 %d부터 검토하지 못했습니다." % (e.status_code, i), "detail": ""})
            return issues, summaries

        if msg.stop_reason == "refusal":
            continue
        text = "".join(b.text for b in msg.content if b.type == "text")
        parsed = parse_json_loose(text)
        if not parsed:
            continue
        if parsed.get("summary_ko"):
            summaries.append("구간 %d (자연스러움 %s/10): %s" % (i, parsed.get("score", "?"), parsed["summary_ko"]))
        for it in parsed.get("issues", []):
            issues.append({
                "level": "warn",
                "check": "일본어 자연스러움",
                "time": "-",
                "msg": "[%s] %s" % (it.get("type", "기타"), it.get("reason_ko", "")),
                "detail": "원문: %s\n수정안: %s" % (it.get("original", ""), it.get("suggestion", "")),
            })
    return issues, summaries


def write_manual_review_request(folder, script_text):
    """API 키가 없을 때: Claude에 붙여넣을 검토요청 파일 생성"""
    req = (
        "아래 일본어 유튜브 내레이션 원고를, 일본 원어민 편집자의 관점에서 검토해줘.\n"
        "50~70대 일본인 시청자 대상이야. 번역투, 어색한 표현, 경어 불일치, 카타카나 과다 사용을 전부 찾아서\n"
        "[원문 → 수정안 → 한국어 설명] 형식으로 정리해줘. 마지막에 전체 자연스러움 점수(10점 만점)와 총평도 부탁해.\n"
        "\n----- 원고 시작 -----\n"
        + script_text
        + "\n----- 원고 끝 -----\n"
    )
    out = Path(folder) / "자연스러움_검토요청.txt"
    out.write_text(req, encoding="utf-8")
    return out


# ---------------------------------------------------------------- 보고서

REPORT_CSS = """
  body { margin:0; background:#f4f5f7; color:#222;
         font-family:"Apple SD Gothic Neo","Malgun Gothic","맑은 고딕",sans-serif; line-height:1.7; }
  .wrap { max-width:960px; margin:0 auto; padding:24px 16px 60px; }
  .card { background:#fff; border:1px solid #e3e5e8; border-radius:12px; padding:24px 28px; margin-bottom:18px; }
  h1 { font-size:22px; margin:0 0 6px; }
  h2 { font-size:17px; margin:0 0 14px; padding-bottom:10px; border-bottom:1px solid #eee; }
  .meta { color:#666; font-size:13px; }
  .badges { margin:14px 0 0; }
  .badge { display:inline-block; padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; margin-right:8px; }
  .b-err { background:#fdecea; color:#c0392b; } .b-warn { background:#fef5e7; color:#b9770e; }
  .b-ok { background:#eafaf1; color:#1e8449; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #f0f0f0; vertical-align:top; }
  th { color:#888; font-weight:600; font-size:12px; }
  td.t { white-space:nowrap; color:#555; }
  .lv { font-weight:700; white-space:nowrap; }
  .lv-error { color:#c0392b; } .lv-warn { color:#b9770e; }
  .detail { color:#666; font-size:13px; white-space:pre-wrap; margin-top:2px; }
  .ok-line { color:#1e8449; font-weight:600; }
  .thumbs { display:flex; flex-wrap:wrap; gap:10px; }
  .thumb { width:220px; font-size:12px; color:#555; }
  .thumb img { width:100%; border-radius:6px; border:1px solid #ddd; }
  .note { background:#f8f9fa; border-radius:8px; padding:12px 16px; font-size:13px; color:#555; }
  .summary-item { margin-bottom:8px; }
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_report(folder, mats, issues, summaries, thumbs, checks_run, checks_skipped):
    errors = [i for i in issues if i["level"] == "error"]
    warns = [i for i in issues if i["level"] == "warn"]

    def issue_rows(check_name):
        rows = [i for i in issues if i["check"] == check_name]
        if not rows:
            return '<p class="ok-line">문제가 발견되지 않았습니다.</p>'
        out = ["<table><tr><th>시각</th><th>구분</th><th>내용</th></tr>"]
        for i in rows:
            out.append(
                '<tr><td class="t">%s</td><td class="lv lv-%s">%s</td><td>%s<div class="detail">%s</div></td></tr>'
                % (esc(i["time"]), i["level"], "오류" if i["level"] == "error" else "확인필요",
                   esc(i["msg"]), esc(i["detail"])))
        out.append("</table>")
        return "".join(out)

    sections = []
    for name in ("자막-대본 대조", "이미지-영상 매칭", "자막 위치", "일본어 자연스러움"):
        if name in checks_skipped:
            body = '<div class="note">%s</div>' % esc(checks_skipped[name])
        else:
            body = issue_rows(name)
            if name == "일본어 자연스러움" and summaries:
                body = "".join('<div class="summary-item">%s</div>' % esc(s) for s in summaries) + body
        sections.append('<div class="card"><h2>%s</h2>%s</div>' % (esc(name), body))

    thumb_html = ""
    if thumbs:
        items = "".join(
            '<div class="thumb"><img src="data:image/jpeg;base64,%s"><div>%s<br>%s</div></div>'
            % (t["b64"], esc(t["time"]), esc(t["text"])) for t in thumbs)
        thumb_html = ('<div class="card"><h2>자막 화면 타임라인 (눈으로 최종 확인용)</h2>'
                      '<div class="thumbs">%s</div></div>' % items)

    files_html = "".join(
        "<div>%s: %s</div>" % (esc(k), esc(v.name if isinstance(v, Path) else
                                           ("%d개" % len(v) if isinstance(v, list) else "없음")))
        for k, v in (("영상", mats["video"] or "없음"), ("이미지", mats["images"]),
                     ("대본", mats["script"] or "없음"), ("자막(SRT)", mats["srt"] or "없음"),
                     ("매칭표", mats["mapping"] or "없음")))

    html = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>영상 검토 보고서</title><style>%s</style></head>
<body><div class="wrap">
  <div class="card">
    <h1>일본 영상 검토 보고서</h1>
    <div class="meta">%s · 검토 폴더: %s</div>
    <div class="badges">
      <span class="badge b-err">오류 %d건</span>
      <span class="badge b-warn">확인 필요 %d건</span>
      <span class="badge b-ok">수행한 검사 %d개</span>
    </div>
    <div class="note" style="margin-top:14px">%s</div>
  </div>
  %s
  %s
</div></body></html>""" % (
        REPORT_CSS,
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        esc(str(folder)),
        len(errors), len(warns), len(checks_run),
        files_html,
        "".join(sections),
        thumb_html,
    )
    out = Path(folder) / "검토보고서.html"
    out.write_text(html, encoding="utf-8")
    return out


# ---------------------------------------------------------------- 메인


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    no_ai = "--no-ai" in args
    folder = Path([a for a in args if not a.startswith("--")][0])
    if not folder.is_dir():
        print("폴더를 찾을 수 없습니다: %s" % folder)
        return

    print("검토 자료를 찾는 중...")
    mats = find_materials(folder)
    for label, val in (("영상", mats["video"]), ("대본", mats["script"]),
                       ("자막(SRT)", mats["srt"]), ("매칭표", mats["mapping"])):
        print("  %s: %s" % (label, val.name if val else "(없음)"))
    print("  이미지: %d개" % len(mats["images"]))

    issues = []
    summaries = []
    thumbs = []
    checks_run = []
    checks_skipped = {}

    script_text = read_text_any_encoding(mats["script"]) if mats["script"] else ""
    cues = parse_srt(read_text_any_encoding(mats["srt"])) if mats["srt"] else []

    # 1. 자막-대본 대조
    if cues and script_text:
        print("1) 자막-대본 대조 중... (자막 %d개)" % len(cues))
        issues += check_subtitles_vs_script(cues, script_text)
        checks_run.append("자막-대본 대조")
    else:
        checks_skipped["자막-대본 대조"] = (
            "대본(.txt)과 자막(.srt)이 둘 다 있어야 하는 검사입니다. "
            "Vrew에서 [파일 > 다른 형식으로 내보내기 > 자막파일(.srt)]로 자막을 내보내 폴더에 넣어 주세요.")

    # 2. 이미지-영상 매칭
    frames, duration = ([], 0.0)
    if mats["video"] and mats["images"]:
        print("2) 영상 분석 중... (1초 간격 샘플링, 시간이 좀 걸립니다)")
        frames, duration = sample_video_frames(mats["video"])
        print("   영상 길이 약 %s, 표본 %d장" % (fmt_time(duration), len(frames)))
        mapping = parse_mapping(mats["mapping"], script_text) if (mats["mapping"] and script_text) else []
        if mapping and cues:
            mapping = expected_scene_times(mapping, cues)
        img_issues, _appear = check_images(mats["images"], frames, mapping, cues, duration)
        issues += img_issues
        checks_run.append("이미지-영상 매칭")
    else:
        checks_skipped["이미지-영상 매칭"] = "영상 파일과 이미지들이 폴더에 있어야 하는 검사입니다."

    # 3. 자막 위치
    if mats["video"] and cues:
        print("3) 자막 위치 점검 중...")
        pos_issues, ocr_note = check_subtitle_positions(mats["video"], cues)
        issues += pos_issues
        thumbs = build_contact_sheet(mats["video"], cues)
        if ocr_note:
            checks_run.append("자막 위치")
        else:
            checks_skipped["자막 위치"] = (
                "자동 위치 검사는 OCR(Tesseract 일본어)이 설치된 경우에만 동작합니다. "
                "대신 아래 [자막 화면 타임라인]으로 위치를 한눈에 확인할 수 있게 넣어 두었습니다.")
    else:
        checks_skipped["자막 위치"] = "영상 파일과 자막(.srt)이 있어야 하는 검사입니다."

    # 4. 일본어 자연스러움
    if script_text and not no_ai:
        api_key = find_api_key()
        if api_key:
            try:
                import anthropic  # noqa
                nat_issues, summaries = check_naturalness(script_text, api_key)
                issues += nat_issues
                checks_run.append("일본어 자연스러움")
            except ImportError:
                checks_skipped["일본어 자연스러움"] = "anthropic 라이브러리가 없습니다. install.bat 을 다시 실행해 주세요."
        else:
            req_path = write_manual_review_request(folder, script_text)
            checks_skipped["일본어 자연스러움"] = (
                "API 키가 없어 자동 검토 대신 [%s] 파일을 만들어 두었습니다. "
                "이 파일 내용을 Claude에 붙여넣으면 원어민 관점 검토를 받을 수 있습니다. "
                "(자동화하려면 프로그램 폴더에 api_key.txt 파일을 만들고 Anthropic API 키를 넣어 주세요)"
                % req_path.name)
    elif no_ai:
        checks_skipped["일본어 자연스러움"] = "--no-ai 옵션으로 건너뛰었습니다."
    else:
        checks_skipped["일본어 자연스러움"] = "대본(.txt)이 있어야 하는 검사입니다."

    report = build_report(folder, mats, issues, summaries, thumbs, checks_run, checks_skipped)
    errors = sum(1 for i in issues if i["level"] == "error")
    warns = sum(1 for i in issues if i["level"] == "warn")
    print("")
    print("검토 완료! 오류 %d건, 확인 필요 %d건" % (errors, warns))
    print("보고서: %s" % report)


if __name__ == "__main__":
    main()
