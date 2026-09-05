# -*- coding: utf-8 -*-
"""
동영상 내용 검사 모듈 (japan_review.py에서 사용)

완성본 동영상(.mp4)을 실제로 열어서:
  1. 씬 전환 시점을 감지하고 (장면이 바뀌는 순간)
  2. 각 장면이 프로젝트의 어떤 이미지인지 대조해서 누락·순서 뒤바뀜을 찾고
  3. 자막이 화면 어디에 표시되는지(하단 안전영역인지), 안 보이는 구간은 없는지
  4. 타임라인 표가 있으면 실제 전환 시점과 맞는지
확인합니다. ffmpeg(imageio-ffmpeg 설치 시 자동 포함)가 필요합니다.
"""

import re
import shutil
import subprocess
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    Image = None

# 분석용 축소 해상도 (비율은 16:9 기준으로 통일해서 비교)
SMALL = (160, 90)
CUT_MIN_DIFF = 15.0        # 이 값 이상 화면이 변하면 '장면 전환' 후보
HASH_MATCH_MAX = 20        # dHash 해밍거리 - 이보다 크면 '다른 그림'
SUB_ROW_DIFF = 9.0         # 자막 감지: 행 평균 밝기 차이 기준
SUB_SAMPLES_MAX = 24       # 자막 위치 샘플 검사 개수 (속도를 위해 제한)
SUB_TOP_LIMIT = 0.62       # 자막 세로 중심이 화면 위쪽 62% 안이면 '위쪽 배치'


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def _run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def video_info(ffmpeg, path):
    """(길이초, 가로, 세로) - ffmpeg -i 의 stderr에서 읽는다."""
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
    """1초 간격 흑백 축소 프레임 목록 [(초, PIL이미지), ...]"""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
           "-vf", f"fps=1,scale={SMALL[0]}:{SMALL[1]}", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    r = _run(cmd)
    raw = r.stdout
    n = SMALL[0] * SMALL[1]
    frames = []
    for i in range(len(raw) // n):
        img = Image.frombytes("L", SMALL, raw[i * n:(i + 1) * n])
        frames.append((float(i), img))
    return frames


def frame_at(ffmpeg, path, t, width=480):
    """특정 시각의 프레임 1장 (흑백, 폭 width로 축소)"""
    h = int(width * 9 / 16)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(0.0, t):.2f}", "-i", str(path), "-frames:v", "1",
           "-vf", f"scale={width}:{h}", "-pix_fmt", "gray",
           "-f", "rawvideo", "-"]
    r = _run(cmd, timeout=60)
    if len(r.stdout) < width * h:
        return None
    return Image.frombytes("L", (width, h), r.stdout[:width * h])


def frame_diff(a, b):
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def detect_scenes(frames):
    """[(시작초, 끝초, 대표프레임), ...] - 화면이 크게 바뀌는 지점으로 나눈다."""
    if len(frames) < 2:
        return [(0.0, frames[-1][0] + 1 if frames else 0.0,
                 frames[0][1] if frames else None)]
    diffs = [frame_diff(frames[i - 1][1], frames[i][1])
             for i in range(1, len(frames))]
    sorted_d = sorted(diffs)
    median = sorted_d[len(sorted_d) // 2]
    threshold = max(CUT_MIN_DIFF, median * 4)
    cuts = [frames[i + 1][0] for i, d in enumerate(diffs) if d >= threshold]
    scenes = []
    start = 0.0
    for c in cuts:
        scenes.append((start, c))
        start = c
    scenes.append((start, frames[-1][0] + 1.0))
    out = []
    for s, e in scenes:
        mid = (s + e) / 2
        rep = min(frames, key=lambda f: abs(f[0] - mid))[1]
        out.append((s, e, rep))
    return out


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


# ── 메인 진입점 ──────────────────────────────────────────────────────────────
def check_video_content(video_path, image_files, sub_cues, timeline_starts,
                        report, section="⑦ 동영상 내용"):
    """
    video_path: 완성본 동영상
    image_files: 프로젝트 이미지 Path 목록
    sub_cues: [(시작초, 끝초, 텍스트), ...] (자막 파일에서)
    timeline_starts: 타임라인 표의 씬 시작 시각(초) 목록 (없으면 [])
    """
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
                f"({size[0]}x{size[1]}, {fmt_t(dur)})" if size
                else f"{Path(video_path).name} ({fmt_t(dur)})")

    frames = sample_frames(ffmpeg, video_path)
    if len(frames) < 2:
        report.add(sec, "오류", "동영상에서 프레임을 읽지 못했습니다")
        return

    # 1) 씬 전환 감지
    scenes = detect_scenes(frames)
    report.stat(sec, "감지된 장면 수", f"{len(scenes)}개 (화면이 크게 바뀐 지점 기준)")

    if image_files:
        n_img = len(image_files)
        if abs(len(scenes) - n_img) > max(1, n_img * 0.15):
            report.add(sec, "주의",
                       f"영상 속 장면 수({len(scenes)}개)와 이미지 수({n_img}장)가 다릅니다",
                       "이미지가 빠졌거나, 인트로/아웃트로 같은 추가 장면이 있거나,\n"
                       "줌·전환 효과 때문에 감지가 어긋났을 수 있습니다. 아래 매칭 결과로 확인하세요.")
        else:
            report.add(sec, "통과", f"장면 수({len(scenes)}개)가 이미지 수({n_img}장)와 비슷합니다")

    # 짧은 장면 (편집 실수로 순간 스치는 장면)
    shorts = [f"{fmt_t(s)}~{fmt_t(e)} ({e - s:.0f}초)"
              for s, e, _ in scenes if (e - s) < 2 and len(scenes) > 1]
    if shorts:
        report.add(sec, "주의", f"2초도 안 되는 짧은 장면이 {len(shorts)}개 있습니다",
                   "\n".join(shorts[:10]))

    # 2) 장면 ↔ 이미지 매칭 (어떤 이미지가 영상에 실제로 나오는지)
    if image_files:
        img_hashes = []
        for f in image_files:
            try:
                with Image.open(f) as im:
                    img_hashes.append((f, dhash(im.convert("L").resize(SMALL))))
            except Exception:
                pass
        matches = []      # (장면번호, 시작, 끝, 매칭파일 or None, 거리)
        for idx, (s, e, rep) in enumerate(scenes, start=1):
            h = dhash(rep)
            best, best_d = None, 999
            for f, ih in img_hashes:
                d = hamming(h, ih)
                if d < best_d:
                    best, best_d = f, d
            if best_d <= HASH_MATCH_MAX:
                matches.append((idx, s, e, best, best_d))
            else:
                matches.append((idx, s, e, None, best_d))

        unmatched_scenes = [f"장면{i} ({fmt_t(s)}~{fmt_t(e)})"
                            for i, s, e, f, _ in matches if f is None]
        used = [f for _, _, _, f, _ in matches if f is not None]
        missing_imgs = [f.name for f, _ in img_hashes if f not in used]
        dup_imgs = sorted({f.name for f in used if used.count(f) > 1})

        # 순서 검사 - 파일명 숫자 기준으로 증가해야 정상
        order_break = []
        prev_num = None
        for i, s, e, f, _ in matches:
            if f is None:
                continue
            nums = re.findall(r"\d+", f.stem)
            if not nums:
                continue
            num = int(nums[-1])
            if prev_num is not None and num < prev_num:
                order_break.append(
                    f"장면{i} ({fmt_t(s)}): {f.name} 이(가) 앞 장면({prev_num:03d})보다 앞 번호")
            prev_num = num

        if missing_imgs:
            report.add(sec, "오류",
                       f"영상에 나오지 않는 이미지가 {len(missing_imgs)}장 있습니다",
                       "편집에서 빠뜨렸을 수 있습니다:\n" + "\n".join(missing_imgs[:15]))
        if order_break:
            report.add(sec, "오류",
                       f"이미지 순서가 뒤바뀐 장면이 {len(order_break)}개 있습니다",
                       "\n".join(order_break[:10]))
        if dup_imgs:
            report.add(sec, "주의",
                       f"같은 이미지가 여러 장면에 나오는 것으로 보입니다 ({len(dup_imgs)}장)",
                       "\n".join(dup_imgs[:10]))
        if unmatched_scenes:
            report.add(sec, "정보",
                       f"프로젝트 이미지와 매칭되지 않은 장면이 {len(unmatched_scenes)}개 있습니다",
                       "인트로/아웃트로/자료 화면이면 정상입니다.\n"
                       + "\n".join(unmatched_scenes[:10]))
        if not missing_imgs and not order_break:
            report.add(sec, "통과",
                       "모든 이미지가 영상에 순서대로 들어가 있습니다")

    # 3) 타임라인 표와 실제 전환 시점 비교
    if timeline_starts:
        cut_times = [s for s, _, _ in scenes[1:]]
        misses = []
        for t in timeline_starts:
            if t <= 0.5:
                continue
            if not any(abs(t - c) <= 1.5 for c in cut_times):
                misses.append(fmt_t(t))
        if misses:
            report.add(sec, "주의",
                       f"타임라인에 적힌 시각에 실제 장면 전환이 없는 곳이 {len(misses)}곳 있습니다",
                       "타임라인 기준 시각: " + ", ".join(misses[:15]))
        else:
            report.add(sec, "통과", "타임라인의 씬 시작 시각과 실제 장면 전환이 일치합니다")

    # 4) 자막 위치·표시 검사 (영상에 구워진 자막)
    if sub_cues:
        _check_burned_subtitles(ffmpeg, video_path, sub_cues, scenes, report, sec)


def _find_gap_time(cue, cues, scene):
    """같은 장면 안에서 자막이 없는 순간을 찾는다. 없으면 None."""
    s_start, s_end = scene
    step = 0.4
    t = s_start + 0.2
    while t < s_end - 0.1:
        if not any(cs - 0.15 <= t <= ce + 0.15 for cs, ce, _ in cues):
            return t
        t += step
    return None


def _check_burned_subtitles(ffmpeg, video_path, cues, scenes, report, sec):
    """자막 표시 구간/비표시 구간 프레임을 비교해서 자막의 실제 위치를 찾는다."""
    # 검사할 자막을 영상 전체에 고르게 분산해서 뽑는다
    usable = [c for c in cues if c[1] - c[0] >= 0.8]
    if not usable:
        return
    step = max(1, len(usable) // SUB_SAMPLES_MAX)
    picked = usable[::step][:SUB_SAMPLES_MAX]

    no_sub, high_pos, off_edge, checked = [], [], [], 0
    for cs, ce, _txt in picked:
        mid = (cs + ce) / 2
        scene = next(((s, e) for s, e, _ in scenes if s <= mid < e), None)
        if scene is None:
            continue
        gap_t = _find_gap_time((cs, ce), cues, scene)
        if gap_t is None:
            continue  # 이 장면은 내내 자막이 있어 비교 기준이 없음
        f_on = frame_at(ffmpeg, video_path, mid)
        f_off = frame_at(ffmpeg, video_path, gap_t)
        if f_on is None or f_off is None:
            continue
        w, h = f_on.size
        diff = ImageChops.difference(f_on, f_off)
        rows = []
        for y in range(h):
            row = diff.crop((0, y, w, y + 1))
            if ImageStat.Stat(row).mean[0] > SUB_ROW_DIFF:
                rows.append(y)
        # 화면 절반 이상이 변했으면 줌·전환 효과라 배경 비교가 성립하지 않음 → 건너뜀
        if len(rows) > h * 0.45 or (rows and rows[-1] - rows[0] > h * 0.6):
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
                   "장면 내내 자막이 있거나 전환 효과가 많으면 비교 기준을 잡을 수 없습니다.")
        return
    report.stat(sec, "자막 위치 검사", f"{checked}곳 표본 검사")
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
