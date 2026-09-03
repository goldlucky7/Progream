# -*- coding: utf-8 -*-
"""
네이버 카페 글 캡쳐 프로그램

로그인이 필요한 네이버 카페 글을 자동으로 열어서
 1) 전체 스크린샷을 찍고
 2) 제목/작성자/본문/이미지를 추출해서
 3) 보기 좋은 HTML 보고서 하나로 정리해 줍니다.

사용법:
  최초 1회 로그인:  python naver_capture.py login
  글 캡쳐:          python naver_capture.py "카페 글 주소"
  여러 개 한번에:    python naver_capture.py "주소1" "주소2" ...
  브라우저 보면서:   python naver_capture.py --show "카페 글 주소"

로그인 정보(비밀번호)는 이 프로그램에 입력하지 않습니다.
login 명령을 실행하면 실제 브라우저 창이 열리고, 거기서 직접 로그인하면
그 로그인 상태만 내 컴퓨터의 browser_profile 폴더에 저장됩니다.
"""

import base64
import datetime
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except ImportError:
    print("playwright가 설치되어 있지 않습니다.")
    print("install.bat 을 실행하거나, 아래 두 명령을 직접 실행해 주세요.")
    print("  python -m pip install -r requirements.txt")
    print("  python -m playwright install chromium")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / "browser_profile"
OUTPUT_DIR = BASE_DIR / "output"

CONTENT_SELECTORS = [
    ".se-main-container",   # 스마트에디터 ONE (요즘 글 대부분)
    "#postViewArea",        # 구버전 에디터
    ".ContentRenderer",     # 신형 카페(ca-fe) 화면
    "#tbody",               # 아주 오래된 글
]
TITLE_SELECTORS = ["h3.title_text", ".title_text", ".ArticleTitle", "h3.tit"]
AUTHOR_SELECTORS = ["button.nickname", ".nickname", ".nick_box", ".profile_info .nick"]
DATE_SELECTORS = [".article_info .date", "span.date", ".date"]


def launch_browser(p, headless):
    return p.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=headless,
        locale="ko-KR",
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
    )


def do_login():
    print("브라우저 창을 엽니다. 열린 창에서 네이버에 로그인해 주세요.")
    print("(비밀번호는 네이버 화면에만 입력하며, 이 프로그램에는 저장되지 않습니다)")
    with sync_playwright() as p:
        ctx = launch_browser(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        for _ in range(300):  # 최대 10분 대기
            time.sleep(2)
            try:
                cookies = ctx.cookies("https://www.naver.com")
            except Exception:
                print("브라우저 창이 닫혔습니다. 로그인 확인 전에 창을 닫으면 저장되지 않을 수 있습니다.")
                return
            if any(c["name"] == "NID_AUT" for c in cookies):
                print("로그인 확인 완료! 이제 링크만 넣으면 캡쳐할 수 있습니다.")
                print('사용 예: python naver_capture.py "카페 글 주소"  (또는 capture.bat 실행)')
                ctx.close()
                return
        print("10분 안에 로그인이 확인되지 않았습니다. 다시 실행해 주세요.")
        ctx.close()


def first_text(page, selectors):
    for sel in selectors:
        try:
            el = page.query_selector(sel)
        except Exception:
            continue
        if el:
            try:
                text = el.inner_text().strip()
            except Exception:
                continue
            if text:
                return text
    return ""


def safe_filename(name, limit=40):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    return (name[:limit] or "제목없음").strip()


def scroll_whole_page(page):
    # 이미지 지연 로딩(lazy load)을 전부 불러오기 위해 끝까지 천천히 스크롤
    try:
        page.evaluate(
            """async () => {
                await new Promise((resolve) => {
                    let scrolled = 0;
                    const timer = setInterval(() => {
                        window.scrollBy(0, 700);
                        scrolled += 700;
                        if (scrolled >= document.body.scrollHeight) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 120);
                });
            }"""
        )
        page.wait_for_timeout(800)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
    except Exception:
        pass


def normalize_lazy_images(page):
    try:
        page.evaluate(
            """() => {
                document.querySelectorAll('img').forEach((img) => {
                    const lazy = img.getAttribute('data-lazy-src')
                        || img.getAttribute('data-src')
                        || img.getAttribute('data-original');
                    if (lazy) img.setAttribute('src', lazy);
                    img.removeAttribute('loading');
                });
            }"""
        )
    except Exception:
        pass


def sanitize_html(html):
    html = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    html = re.sub(r"<iframe\b[^>]*>.*?</iframe>", "", html, flags=re.S | re.I)
    html = re.sub(r'\son\w+\s*=\s*"[^"]*"', "", html, flags=re.I)
    html = re.sub(r"\son\w+\s*=\s*'[^']*'", "", html, flags=re.I)
    return html


def embed_images(ctx, html):
    # 본문 HTML 안의 이미지 주소를 전부 내려받아 base64로 바꿔 넣어서
    # 보고서 파일 하나만으로도 이미지가 보이게 만든다.
    urls = sorted(set(re.findall(r'src="(https?://[^"]+)"', html)))
    for url in urls:
        if any(skip in url for skip in ("cafe.pstatic.net/cf", "static.nid", ".js", ".css")):
            continue
        try:
            resp = ctx.request.get(url, timeout=30000)
            if not resp.ok:
                continue
            body = resp.body()
            if len(body) < 100:
                continue
            ctype = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if not ctype.startswith("image/"):
                continue
            encoded = base64.b64encode(body).decode("ascii")
            html = html.replace('src="%s"' % url, 'src="data:%s;base64,%s"' % (ctype, encoded))
        except Exception:
            continue
    return html


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{
    margin: 0; background: #f4f5f7; color: #222;
    font-family: "Apple SD Gothic Neo", "Malgun Gothic", "맑은 고딕", sans-serif;
    line-height: 1.7;
  }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 24px 16px 60px; }}
  .card {{
    background: #fff; border: 1px solid #e3e5e8; border-radius: 12px;
    padding: 28px 32px; margin-bottom: 20px;
  }}
  h1 {{ font-size: 24px; margin: 0 0 12px; line-height: 1.4; }}
  .meta {{ color: #666; font-size: 14px; border-bottom: 1px solid #eee;
          padding-bottom: 14px; margin-bottom: 20px; }}
  .meta span {{ margin-right: 16px; }}
  .meta a {{ color: #03c75a; text-decoration: none; }}
  .content img {{ max-width: 100%; height: auto; border-radius: 6px; }}
  .content {{ overflow-wrap: break-word; }}
  details {{ margin-top: 8px; }}
  summary {{
    cursor: pointer; font-weight: 600; font-size: 15px;
    padding: 14px 0; color: #444;
  }}
  .shot img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 6px; }}
  .footer {{ color: #999; font-size: 12px; text-align: center; margin-top: 24px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <h1>{title}</h1>
    <div class="meta">
      <span>작성자: {author}</span>
      <span>작성일: {date}</span>
      <span><a href="{url}" target="_blank">원본 글 열기</a></span>
    </div>
    <div class="content">{content}</div>
  </div>
  <div class="card shot">
    <details>
      <summary>원본 화면 전체 스크린샷 펼쳐보기</summary>
      <img src="data:image/png;base64,{screenshot_b64}" alt="원본 스크린샷">
    </details>
  </div>
  <div class="footer">캡쳐 시각: {captured_at}</div>
</div>
</body>
</html>
"""


def capture(url, show=False):
    print("")
    print("캡쳐 시작: %s" % url)
    with sync_playwright() as p:
        ctx = launch_browser(p, headless=not show)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            if "nid.naver.com" in page.url:
                print("로그인이 되어 있지 않습니다. 먼저 login.bat(또는 python naver_capture.py login)을 실행해 주세요.")
                return False

            # 구형 카페 주소는 글이 iframe(cafe_main) 안에 들어있다.
            # iframe이 있으면 그 안의 실제 글 주소로 직접 이동해서 전체 캡쳐가 가능하게 한다.
            frame = page.frame(name="cafe_main")
            if frame and frame.url and frame.url != "about:blank":
                page.goto(frame.url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1000)

            try:
                page.wait_for_selector(", ".join(CONTENT_SELECTORS), timeout=20000)
            except PlaywrightTimeout:
                print("본문 영역을 찾지 못했습니다. (멤버 등급 제한 글이거나 화면 구조가 다른 글일 수 있습니다)")
                print("일단 화면 전체 스크린샷만 저장합니다. --show 옵션으로 다시 시도해 볼 수도 있습니다.")

            scroll_whole_page(page)
            normalize_lazy_images(page)

            title = first_text(page, TITLE_SELECTORS) or page.title() or "제목없음"
            author = first_text(page, AUTHOR_SELECTORS) or "알 수 없음"
            date = first_text(page, DATE_SELECTORS) or "알 수 없음"

            content_html = ""
            for sel in CONTENT_SELECTORS:
                el = page.query_selector(sel)
                if el:
                    content_html = el.inner_html()
                    break
            if not content_html:
                content_html = "<p>(본문을 추출하지 못했습니다. 아래 스크린샷을 확인해 주세요)</p>"

            timestamp = datetime.datetime.now()
            folder = OUTPUT_DIR / ("%s_%s" % (timestamp.strftime("%Y%m%d_%H%M%S"), safe_filename(title)))
            folder.mkdir(parents=True, exist_ok=True)

            shot_path = folder / "screenshot.png"
            page.screenshot(path=str(shot_path), full_page=True)

            content_html = sanitize_html(content_html)
            print("이미지 정리 중...")
            content_html = embed_images(ctx, content_html)

            report = REPORT_TEMPLATE.format(
                title=title,
                author=author,
                date=date,
                url=url,
                content=content_html,
                screenshot_b64=base64.b64encode(shot_path.read_bytes()).decode("ascii"),
                captured_at=timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            )
            report_path = folder / "정리본.html"
            report_path.write_text(report, encoding="utf-8")

            print("완료!")
            print("  정리본:   %s" % report_path)
            print("  스크린샷: %s" % shot_path)
            return True
        except PlaywrightTimeout:
            print("페이지를 여는 데 너무 오래 걸립니다. 인터넷 연결과 주소를 확인한 뒤 다시 시도해 주세요.")
            return False
        finally:
            ctx.close()


def print_usage():
    print(__doc__)


def main():
    args = [a for a in sys.argv[1:]]
    if not args or args[0] in ("-h", "--help", "help"):
        print_usage()
        return
    if args[0] == "login":
        do_login()
        return

    show = "--show" in args
    urls = [a for a in args if a.startswith("http")]
    if not urls:
        print("캡쳐할 주소(http로 시작)를 찾지 못했습니다.")
        print('사용 예: python naver_capture.py "https://cafe.naver.com/카페이름/글번호"')
        return

    if not PROFILE_DIR.exists():
        print("아직 로그인한 적이 없습니다. 먼저 login.bat(또는 python naver_capture.py login)을 실행해 주세요.")
        return

    success = 0
    for url in urls:
        if capture(url, show=show):
            success += 1
    print("")
    print("총 %d개 중 %d개 캡쳐 완료. 결과는 output 폴더에 있습니다." % (len(urls), success))


if __name__ == "__main__":
    main()
