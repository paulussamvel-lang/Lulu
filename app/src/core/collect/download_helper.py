"""Browser-resource download route used by the user's Douyin helper workflow.

Independent implementation: no extension code, account export or browser profile
copy. The existing Lulu browser owns its login and profile lease.
"""
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlsplit


def work_id(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    for key in ('modal_id', 'modalId', 'aweme_id'):
        value = query.get(key, [''])[0]
        if re.fullmatch(r'\d{5,64}', value):
            return value
    match = re.search(r'/(?:video|note)/(\d{5,64})(?:/|$)', parsed.path)
    return match.group(1) if match else ''


def media_choices(video):
    """Prefer real pixel count then bitrate; keep same-work fallback routes."""
    from ..audio.extractor import is_douyin_video_cdn
    rows = []
    rates = video.get('bit_rate') or video.get('bitRate') or []
    entries = [(r.get('play_addr') or r.get('playAddr') or {}, r)
               for r in rates if isinstance(r, dict)] if isinstance(rates, list) else []
    entries += [(video.get(k) or {}, {}) for k in ('play_addr_h264', 'play_addr_265', 'play_addr', 'download_addr')]
    def number(value):
        try: return max(0, int(value))
        except (ValueError, TypeError, OverflowError): return 0
    for address, rate in entries:
        if not isinstance(address, dict): continue
        width = number(address.get('width') or rate.get('width') or video.get('width'))
        height = number(address.get('height') or rate.get('height') or video.get('height'))
        bitrate = number(rate.get('bit_rate') or rate.get('bitRate') or address.get('bit_rate'))
        urls = address.get('url_list') or address.get('urlList') or []
        if not isinstance(urls, list): continue
        for url in urls:
            if (isinstance(url, str) and is_douyin_video_cdn(url)
                    and not re.search(r'(?:mime_type=audio|/audio/|\.m4a(?:\?|$))', url, re.I)):
                rows.append((width * height, bitrate, url))
    seen, result = set(), []
    for _, _, url in sorted(rows, key=lambda row: (row[0], row[1]), reverse=True):
        if url not in seen:
            seen.add(url)
            result.append(url)
    return result


def select_detail(payload, expected):
    if not expected or not isinstance(payload, dict): return None
    candidates = [payload.get('aweme_detail'), *(payload.get('aweme_list') or [])]
    for detail in candidates:
        if isinstance(detail, dict) and str(detail.get('aweme_id', '')) == expected:
            choices = media_choices(detail.get('video') or {})
            if choices:
                return detail, choices
    return None


def resolve_video(url, progress, *, timeout=90, shell_factory=None):
    from .browser_shell import BrowserShell, BrowserLaunchSpec, _default_options_factory
    from .profiles import ProfileRegistry
    from .models import _douyin_cover_url
    from ..models_manager import app_data_dir
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password or len(url) > 4096
            or not any(host == d or host.endswith('.'+d) for d in ('douyin.com', 'iesdouyin.com'))):
        raise ValueError('请提供完整的抖音作品 HTTPS 链接。')
    def options():
        value = _default_options_factory()
        value.headless(False)
        value.set_load_mode('eager')
        value.set_retry(times=0, interval=0)
        value.set_timeouts(base=1, page_load=15, script=2)
        chrome = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
        if chrome.is_file(): value.set_browser_path(str(chrome))
        return value
    factory = shell_factory or (lambda: BrowserShell(ProfileRegistry(app_data_dir()), options_factory=options))
    progress('抖音下载助手方式：打开浏览器识别当前作品与可用画质…', -1)
    with factory().open(BrowserLaunchSpec(platform_id='douyin')) as page:
        page.close_timeout = 2.0
        page.listen.start(['aweme/v1/web/aweme/detail', 'aweme/v1/web/feed'])
        page.get(url)
        deadline, expected = time.monotonic() + timeout, work_id(url)
        while time.monotonic() < deadline:
            progress('正在浏览器中识别作品；若出现登录或验证，请在该窗口完成。', -1)
            expected = expected or work_id(str(page.url))
            packet = page.listen.wait(timeout=.5, raise_err=False)
            if not packet: continue
            selected = select_detail(packet.response.body, expected)
            if selected is None: continue
            detail, choices = selected
            author = detail.get('author') or {}
            stats = detail.get('statistics') or {}
            progress('已识别当前作品，优先保存最高可用画质…', -1)
            return dict(urls=choices, title=str(detail.get('desc') or '抖音视频'),
                work_id=expected, author={'name':str(author.get('nickname') or '')},
                stats={key:stats.get(field) for key,field in [('like','digg_count'),('comment','comment_count'),
                    ('share','share_count'),('collect','collect_count')] if type(stats.get(field)) is int},
                cover=_douyin_cover_url(detail.get('video') or {}))
    raise ValueError('浏览器未返回当前作品的可用视频。请检查登录或验证后重试；未改用其他作品。')
