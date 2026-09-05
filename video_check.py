# -*- coding: utf-8 -*-
"""
동영상 내용 검사 모듈 (japan_review.py에서 사용)

완성본 동영상(.mp4)을 실제로 열어서:
  1. 1초 간격으로 화면을 뽑아 "지금 어떤 이미지가 나오는지"를 프로젝트 이미지와 직접 대조
     (줌·확대 효과, 크로스페이드 전환이 있어도 동작하도록 설계)
  2. 빠진 이미지 · 순서 뒤바뀜 · 중복 사용을 찾고
  3. 자막이 화면 어디에 표시되는지(하단 안전영역인지), 안 보이는 자막은 없는지
  4. 타임라인 표가 있으면 실제 장면 전환 시점과 맞는지
확인합니다. ffmpeg(imageio-ffmpeg 설치 시 자동 포함)가 필요합니다.
"""

import re
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageStat, ImageFilter
except ImportError:
    Image = None

SMALL = (160, 90)          # 분석용 축소 해상도 (16:9 기준으로 통일)
HASH_MATCH_MAX = 26        # dHash 해밍거리 - 이보다 크면 '이 이미지가 아님' (줌 감안 여유)
CUT_HASH_MIN = 10          # 이미지 없이 전환 감지할 때의 해시 변화 기준
SUB_SAMPLES_MAX = 24       # 자막 위치 표본 검사 개수
SUB_TOP_LIMIT = 0.62       # 자막 세로 중심이 화면 위쪽 62% 안이면 '위쪽 배치'
MIN_SCENE_SEC = 2.0        # 이보다 짧은 장면 구간은 전환 효과로 보고 이웃에 흡수


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _run(cmd, timeout=900):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def video_info(ffmpeg, path):
    r = _run([ffmpeg, "-hide_banner", "-i", str(path)], timeout=60)
    text = r.stderr.decode("utf-8", errors="replace")
    dur = None
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        h, mi, s = m.groups()
        dur = int(h) * 3600 + int(mi) * 60 + float(s)
    size = None
    m = re.search(r"Video:.*?\s(\d{2,5})x(\d{2,5})", text)
    if m:
        size = (int(m.group(1)), int(m.group(2)))
    return dur, size


def sample_frames(ffmpeg, path):
    """1초 간격 흑백 축소 프레임 [(초, PIL이미지), ...]"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
           "-vf", f"fps=1,scale={SMALL[0]}:{SMALL[1]}", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    r = _run(cmd)
    raw = r.stdout
    n = SMALL[0] * SMALL[1]
    return [(float(i), Image.frombytes("L", SMALL, raw[i * n:(i + 1) * n]))
            for i in range(len(raw) // n)]


def frame_at(ffmpeg, path, t, width=480):
    """특정 시각의 프레임 1장 (흑백, 폭 width 축소)"""
    h = int(width * 9 / 16)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(0.0, t):.2f}", "-i", str(path), "-frames:v", "1",
           "-vf", f"scale={width}:{h}", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    r = _run(cmd, timeout=60)
    if len(r.stdout) < width * h:
        return None
    return Image.frombytes("L", (width, h), r.stdout[:width * h])


def dhash(img):
    small = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def fmt_t(sec):
    m, s = divmod(int(round(sec)), 60)
    return f"{m}:{s:02d}"


# ── 장면 분석: 매 초 프레임을 이미지와 직접 대조 ────────────────────────────
def label_frames(frames, img_hashes):
    """각 프레임에 (가장 비슷한 이미지 파일 or None) 라벨을 붙인다."""
    labels = []
    for _t, img in frames:
        h = dhash(img)
        best, best_d = None, 999
        for f, ih in img_hashes:
            d = hamming(h, ih)
            if d < best_d:
                best, best_d = f, d
        labels.append(best if best_d <= HASH_MATCH_MAX else None)
    # 한 프레임짜리 라벨 튐(페이드 순간 등)은 양옆 라벨로 메꾼다
    for i in range(1, len(labels) - 1):
        if labels[i] != labels[i - 1] and labels[i - 1] == labels[i + 1]:
            labels[i] = labels[i - 1]
    return labels


def build_segments(frames, labels):
    """라벨이 이어지는 구간으로 장면을 나눈다. [(시작, 끝, 라벨), ...]"""
    segs = []
    start = frames[0][0]
    cur = labels[0]
    for i in range(1, len(labels)):
        if labels[i] != cur:
            segs.append([start, frames[i][0], cur])
            start, cur = frames[i][0], labels[i]
    segs.append([start, frames[-1][0] + 1.0, cur])
    # 너무 짧은 구간(전환 효과의 흔적)은 앞 구간에 흡수
    merged = []
    for s in segs:
        if merged and (s[1] - s[0]) < MIN_SCENE_SEC and s[2] is None:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    # 같은 라벨이 연달아 남았으면 합침
    out = []
    for s in merged:
        if out and out[-1][2] == s[2]:
            out[-1][1] = s[1]
        else:
            out.append(s)
    return [(s, e, lb) for s, e, lb in out]


def detect_cuts_no_images(frames):
    """이미지가 없을 때: 해시 변화가 주변보다 튀는 지점을 전환으로 본다."""
    hashes = [dhash(img) for _t, img in frames]
    diffs = [hamming(hashes[i - 1], hashes[i]) for i in range(1, len(hashes))]
    if not diffs:
        return []
    sd = sorted(diffs)
    median = sd[len(sd) // 2]
    threshold = max(CUT_HASH_MIN, median * 3)
    cuts = []
    for i, d in enumerate(diffs):
        t = frames[i + 1][0]
        if d >= threshold and (not cuts or t - cuts[-1] >= MIN_SCENE_SEC):
            cuts.append(t)
    return cuts


# ── 메인 진입점 ──────────────────────────────────────────────────────────────
def check_video_content(video_path, image_files, sub_cues, timeline_starts,
                        report, section="⑦ 동영상 내용"):
    sec = section
    if Image is None:
        report.add(sec, "주의", "Pillow가 없어 동영상 내용 검사를 건너뜁니다",
                   "install_review.bat 을 다시 실행해 주세요.")
        return
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        report.add(sec, "주의", "ffmpeg이 없어 동영상 내용 검사를 건너뜁니다",
                   "install_review.bat 을 다시 실행하면 자동으로 설치됩니다.")
        return

    dur, size = video_info(ffmpeg, video_path)
    if not dur:
        report.add(sec, "오류", f"동영상을 열 수 없습니다: {Path(video_path).name}")
        return
    report.stat(sec, "동영상", f"{Path(video_path).name} "
                + (f"({size[0]}x{size[1]}, {fmt_t(dur)})" if size else f"({fmt_t(dur)})"))

    frames = sample_frames(ffmpeg, video_path)
    if len(frames) < 2:
        report.add(sec, "오류", "동영상에서 프레임을 읽지 못했습니다")
        return

    img_hashes = []
    for f in image_files:
        try:
            with Image.open(f) as im:
                img_hashes.append((f, dhash(im.convert("L").resize(SMALL))))
        except Exception:
            pass

    scenes = []          # (시작, 끝) - 자막 검사용
    cut_times = []
    if img_hashes:
        labels = label_frames(frames, img_hashes)
        segments = build_segments(frames, labels)
        scenes = [(s, e) for s, e, _ in segments]
        cut_times = [s for s, _, _ in segments[1:]]

        matched_segs = [(s, e, lb) for s, e, lb in segments if lb is not None]
        report.stat(sec, "감지된 장면", f"{len(matched_segs)}개 (이미지와 대조해서 인식)")

        # 나오지 않는 이미지 / 순서 / 중복
        used_files = [lb for _s, _e, lb in matched_segs]
        missing = [f.name for f, _ in img_hashes if f not in used_files]
        dups = sorted({f.name for f in used_files if used_files.count(f) > 1})
        order_break = []
        prev_num = None
        for s, e, lb in matched_segs:
            nums = re.findall(r"\d+", lb.stem)
            if not nums:
                continue
            num = int(nums[-1])
            if prev_num is not None and num < prev_num:
                order_break.append(
                    f"{fmt_t(s)}부터 {lb.name} - 앞 장면({prev_num:03d})보다 앞 번호")
            prev_num = num
        unmatched = [(s, e) for s, e, lb in segments if lb is None and e - s >= 3]

        if missing:
            report.add(sec, "오류",
                       f"영상에 나오지 않는 이미지가 {len(missing)}장 있습니다",
                       "편집에서 빠뜨렸을 수 있습니다:\n" + "\n".join(missing[:15]))
        if order_break:
            report.add(sec, "오류",
                       f"이미지 순서가 뒤바뀐 장면이 {len(order_break)}개 있습니다",
                       "\n".join(order_break[:10]))
        if dups:
            report.add(sec, "주의",
                       f"같은 이미지가 여러 장면에 나오는 것으로 보입니다 ({len(dups)}장)",
                       "\n".join(dups[:10]))
        if unmatched:
            report.add(sec, "정보",
                       f"프로젝트 이미지와 매칭되지 않은 구간이 {len(unmatched)}곳 있습니다",
                       "인트로/아웃트로/자료 화면이면 정상입니다.\n"
                       + "\n".join(f"{fmt_t(s)}~{fmt_t(e)}" for s, e in unmatched[:10]))
        if not missing and not order_break:
            report.add(sec, "통과", "모든 이미지가 영상에 순서대로 들어가 있습니다")

        # 장면 길이 이상 (편집 실수로 순간 스치는 장면)
        shorts = [f"{fmt_t(s)}~{fmt_t(e)} ({lb.name}, {e - s:.0f}초)"
                  for s, e, lb in matched_segs if (e - s) < MIN_SCENE_SEC]
        if shorts:
            report.add(sec, "주의", f"2초도 안 되는 짧은 장면이 {len(shorts)}개 있습니다",
                       "\n".join(shorts[:10]))
    else:
        cut_times = detect_cuts_no_images(frames)
        starts = [0.0] + cut_times
        ends = cut_times + [frames[-1][0] + 1.0]
        scenes = list(zip(starts, ends))
        report.stat(sec, "감지된 장면", f"{len(scenes)}개 (화면 변화 기준, 이미지 없이 추정)")

    # 타임라인 표와 실제 전환 시점 비교
    if timeline_starts and cut_times:
        misses = [fmt_t(t) for t in timeline_starts
                  if t > 0.5 and not any(abs(t - c) <= 2.0 for c in cut_times)]
        if misses:
            report.add(sec, "주의",
                       f"타임라인에 적힌 시각에 실제 장면 전환이 없는 곳이 {len(misses)}곳 있습니다",
                       "타임라인 기준 시각: " + ", ".join(misses[:15]))
        else:
            report.add(sec, "통과", "타임라인의 씬 시작 시각과 실제 장면 전환이 일치합니다")

    # 자막 위치·표시 검사
    if sub_cues and scenes:
        _check_burned_subtitles(ffmpeg, video_path, sub_cues, scenes, report, sec)


# ── 자막 위치 검사 ───────────────────────────────────────────────────────────
def _nearest_gap_time(cue, cues, scene):
    """자막이 꺼져 있는 순간 중, 이 자막과 시간상 가장 가까운 순간을 찾는다.
    (줌 효과 중에도 배경이 거의 같도록 가까운 시각을 고른다)"""
    cs, ce = cue
    s_start, s_end = scene

    def free(t):
        return (s_start + 0.1 <= t <= s_end - 0.1
                and not any(a - 0.2 <= t <= b + 0.2 for a, b, _ in cues))

    for delta in (0.5, 0.8, 1.2, 1.8, 2.5):
        for t in (cs - delta, ce + delta):
            if free(t):
                return t
    return None


def _row_profile(f_on, f_off):
    """두 프레임 차이의 행별 평균 밝기. 부드럽게 블러 후 비교."""
    a = f_on.filter(ImageFilter.GaussianBlur(1.2))
    b = f_off.filter(ImageFilter.GaussianBlur(1.2))
    diff = ImageChops.difference(a, b)
    w, h = diff.size
    return [ImageStat.Stat(diff.crop((0, y, w, y + 1))).mean[0] for y in range(h)], h


def _check_burned_subtitles(ffmpeg, video_path, cues, scenes, report, sec):
    usable = [c for c in cues if c[1] - c[0] >= 0.8]
    if not usable:
        return
    step = max(1, len(usable) // SUB_SAMPLES_MAX)
    picked = usable[::step][:SUB_SAMPLES_MAX]

    no_sub, high_pos, off_edge, skipped = [], [], [], 0
    checked = 0
    for cs, ce, _txt in picked:
        mid = (cs + ce) / 2
        scene = next(((s, e) for s, e in scenes if s <= mid < e), None)
        if scene is None:
            skipped += 1
            continue
        gap_t = _nearest_gap_time((cs, ce), cues, scene)
        if gap_t is None:
            skipped += 1
            continue
        # 자막 프레임은 자막이 완전히 표시된 순간을 고른다 (등장 애니메이션 회피)
        t_on = min(max(cs + 0.6, mid), ce - 0.3)
        f_on = frame_at(ffmpeg, video_path, t_on)
        f_off = frame_at(ffmpeg, video_path, gap_t)
        if f_on is None or f_off is None:
            skipped += 1
            continue
        profile, h = _row_profile(f_on, f_off)
        sp = sorted(profile)
        base_level = sp[len(sp) // 2]                     # 배경 흔들림(줌 등) 수준
        threshold = max(10.0, base_level * 3 + 6)
        rows = [y for y, v in enumerate(profile) if v > threshold]
        # 화면 절반 이상이 변했으면 전환·큰 움직임이라 판정 불가
        if len(rows) > h * 0.45 or (rows and rows[-1] - rows[0] > h * 0.6):
            skipped += 1
            continue
        checked += 1
        label = f"{fmt_t(cs)} 자막"
        if not rows:
            no_sub.append(label)
            continue
        center = (rows[0] + rows[-1]) / 2 / h
        bottom = rows[-1] / h
        if center < SUB_TOP_LIMIT:
            high_pos.append(f"{label}: 세로 {center:.0%} 지점(위쪽)에 표시됨")
        if bottom > 0.985:
            off_edge.append(f"{label}: 화면 맨 아래에 붙어 있음(잘릴 위험)")

    if checked == 0:
        report.add(sec, "정보", "자막 위치를 판정할 수 있는 장면이 없었습니다",
                   "장면 내내 자막이 있거나 전환·움직임 효과가 많으면 비교 기준을 잡을 수 없습니다.")
        return
    note = f"{checked}곳 표본 검사" + (f" (효과 등으로 판정 불가 {skipped}곳 제외)" if skipped else "")
    report.stat(sec, "자막 위치 검사", note)
    if no_sub:
        report.add(sec, "오류",
                   f"자막 파일에는 있는데 영상 화면에 안 보이는 자막이 {len(no_sub)}곳 있습니다"
                   f" (표본 {checked}곳 중)",
                   "자막을 입히지 않고 내보냈거나, 일부 구간이 빠졌을 수 있습니다.\n"
                   + "\n".join(no_sub[:10]))
    if high_pos:
        report.add(sec, "주의",
                   f"화면 위쪽에 표시되는 자막이 {len(high_pos)}곳 있습니다 (표본 {checked}곳 중)",
                   "이미지의 중요한 부분을 가릴 수 있습니다.\n" + "\n".join(high_pos[:10]))
    if off_edge:
        report.add(sec, "주의",
                   f"화면 맨 끝에 붙은 자막이 {len(off_edge)}곳 있습니다",
                   "\n".join(off_edge[:10]))
    if not no_sub and not high_pos and not off_edge:
        report.add(sec, "통과",
                   f"표본 {checked}곳 모두 자막이 하단 정상 위치에 표시되고 있습니다")
