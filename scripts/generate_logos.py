#!/usr/bin/env python3

import argparse
import csv
import io
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, unquote, urlencode

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

DDG_HTML_SEARCH = "https://duckduckgo.com/html/"

# Prefer lxml if available; otherwise fallback to built-in html.parser
try:
    import lxml  # type: ignore  # noqa: F401
    DEFAULT_SOUP_PARSER = "lxml"
except Exception:
    DEFAULT_SOUP_PARSER = "html.parser"


@dataclass
class PropertyRow:
    property_name: str
    city: str
    district: str
    website: str


@dataclass
class ProcessResult:
    status: str
    source: str
    source_url: str
    saved_path: str
    notes: str


def log_info(message: str) -> None:
    print(message, flush=True)


def ensure_dir(path: str) -> None:
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def create_session(timeout_seconds: int = 15) -> requests.Session:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.7,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Connection": "keep-alive",
        }
    )
    session.request = _wrap_request_with_timeout(session.request, timeout_seconds)
    return session


def _wrap_request_with_timeout(request_func, timeout_seconds: int):
    def _request_with_timeout(method, url, **kwargs):
        if "timeout" not in kwargs:
            kwargs["timeout"] = timeout_seconds
        return request_func(method, url, **kwargs)

    return _request_with_timeout


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\-]", "", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-") or "logo"


def read_csv(path: str) -> List[PropertyRow]:
    rows: List[PropertyRow] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"property_name", "city", "district", "website"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
        for r in reader:
            rows.append(
                PropertyRow(
                    property_name=r.get("property_name", "").strip(),
                    city=r.get("city", "").strip(),
                    district=r.get("district", "").strip(),
                    website=r.get("website", "").strip(),
                )
            )
    return rows


def normalize_url(url: str, base_url: Optional[str] = None) -> Optional[str]:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if base_url and not bool(urlparse(url).netloc):
        url = urljoin(base_url, url)
    # Remove fragments
    parsed = urlparse(url)
    url = parsed._replace(fragment="").geturl()
    return url


def is_probable_profile_instagram_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if "instagram.com" not in host:
            return False
        path = parsed.path.strip("/")
        if not path:
            return False
        # reject known non-profile paths
        bad_prefixes = (
            "explore/",
            "p/",
            "reel/",
            "reels/",
            "stories/",
            "tv/",
            "tags/",
            "directory/",
        )
        for b in bad_prefixes:
            if path.startswith(b):
                return False
        # profile path should be single segment (username) or username/verified/ etc.
        segments = [seg for seg in path.split("/") if seg]
        return len(segments) == 1
    except Exception:
        return False


def ddg_search_first_instagram(session: requests.Session, query: str) -> Optional[str]:
    params = {"q": query}
    try:
        resp = session.get(DDG_HTML_SEARCH, params=params)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, DEFAULT_SOUP_PARSER)
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            # DuckDuckGo html result links often are /l/?kh=-1&uddg=<urlencoded>
            parsed = urlparse(href)
            if parsed.path == "/l/" and "uddg" in parse_qs(parsed.query):
                uddg = parse_qs(parsed.query).get("uddg", [""])[0]
                actual_url = unquote(uddg)
            else:
                actual_url = href
            actual_url = normalize_url(actual_url)
            if not actual_url:
                continue
            if "instagram.com" in actual_url and is_probable_profile_instagram_url(actual_url):
                return actual_url
    except Exception:
        return None
    return None


def fetch_html(session: requests.Session, url: str) -> Tuple[Optional[BeautifulSoup], Optional[str]]:
    try:
        resp = session.get(url, allow_redirects=True)
        if resp.status_code != 200:
            return None, None
        final_url = resp.url
        return BeautifulSoup(resp.text, DEFAULT_SOUP_PARSER), final_url
    except Exception:
        return None, None


def find_instagram_on_website(session: requests.Session, website_url: str) -> Optional[str]:
    soup, final_url = fetch_html(session, website_url)
    if not soup:
        return None
    base = final_url or website_url

    # Look for anchors with instagram
    for a in soup.select("a[href]"):
        href = a.get("href")
        norm = normalize_url(href, base)
        if not norm:
            continue
        if "instagram.com" in norm:
            # sanitize to profile root if possible
            norm = norm.split("?", 1)[0]
            norm = norm if norm.endswith("/") else norm + "/"
            # Remove extra path segments if it looks like /username/...
            try:
                parsed = urlparse(norm)
                segments = [s for s in parsed.path.split("/") if s]
                if segments:
                    candidate = f"{parsed.scheme}://{parsed.netloc}/{segments[0]}/"
                else:
                    candidate = norm
            except Exception:
                candidate = norm
            if is_probable_profile_instagram_url(candidate):
                return candidate
    return None


def extract_instagram_profile_image(session: requests.Session, profile_url: str) -> Optional[Tuple[bytes, str]]:
    # Try official web_profile_info endpoint (often works without login)
    try:
        parsed = urlparse(profile_url)
        username = [s for s in parsed.path.split("/") if s]
        if username:
            username = username[0]
            api_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
            headers = {
                "User-Agent": DEFAULT_USER_AGENT,
                "X-IG-App-ID": "936619743392459",
                "Accept": "*/*",
                "Referer": f"https://www.instagram.com/{username}/",
            }
            r = session.get(api_url, headers=headers)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                data = r.json()
                user = data.get("data", {}).get("user", {})
                pic_hd = user.get("profile_pic_url_hd") or user.get("profile_pic_url")
                if pic_hd:
                    img_bytes, ext = download_image(session, pic_hd)
                    if img_bytes:
                        return img_bytes, ext
    except Exception:
        pass

    # Fallback: parse the profile page HTML for og:image or JSON-LD
    try:
        soup, final_url = fetch_html(session, profile_url)
        if not soup:
            return None
        # Try og:image
        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            img_url = normalize_url(og["content"], final_url)
            if img_url:
                img_bytes, ext = download_image(session, img_url)
                if img_bytes:
                    return img_bytes, ext
        # Try JSON-LD image
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                import json

                data = json.loads(script.text)
                if isinstance(data, dict):
                    img = data.get("image")
                    if isinstance(img, str):
                        img_url = normalize_url(img, final_url)
                        img_bytes, ext = download_image(session, img_url)
                        if img_bytes:
                            return img_bytes, ext
            except Exception:
                continue
    except Exception:
        return None
    return None


def guess_extension_from_content_type(content_type: str) -> str:
    content_type = (content_type or "").lower()
    if "jpeg" in content_type or content_type.endswith("/jpg"):
        return ".jpg"
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "svg" in content_type:
        return ".svg"
    if "x-icon" in content_type or content_type.endswith("/ico"):
        return ".ico"
    if "gif" in content_type:
        return ".gif"
    return ".img"


def sanitize_image_extension_from_url(url: str) -> Optional[str]:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".svg", ".ico", ".gif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return None


def download_image(session: requests.Session, url: str) -> Tuple[Optional[bytes], Optional[str]]:
    try:
        r = session.get(url, stream=True)
        if r.status_code != 200:
            return None, None
        content_type = r.headers.get("content-type", "")
        ext = sanitize_image_extension_from_url(url) or guess_extension_from_content_type(content_type)
        content = r.content
        if not content or len(content) < 100:
            return None, None
        return content, ext
    except Exception:
        return None, None


def extract_best_logo_from_website(session: requests.Session, website_url: str) -> Optional[Tuple[bytes, str]]:
    soup, final_url = fetch_html(session, website_url)
    if not soup:
        return None
    base = final_url or website_url

    candidates: List[Tuple[str, int]] = []

    def add_candidate(u: Optional[str], weight: int) -> None:
        if not u:
            return
        candidates.append((normalize_url(u, base) or u, weight))

    # Icons
    for rel in ["icon", "shortcut icon", "apple-touch-icon", "apple-touch-icon-precomposed", "mask-icon"]:
        for link in soup.find_all("link", attrs={"rel": re.compile(fr"(^|\s){re.escape(rel)}(\s|$)", re.I)}):
            href = link.get("href")
            sizes = link.get("sizes", "")
            weight = 50
            try:
                if sizes:
                    # prefer larger sizes
                    nums = re.findall(r"(\d+)", sizes)
                    if nums:
                        size = max(int(n) for n in nums)
                        weight += min(size, 1024)
            except Exception:
                pass
            add_candidate(href, weight)

    # og:image
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content"):
        add_candidate(og["content"], 300)

    # img tags with logo-ish hints
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue
        attrs = " ".join(
            [
                (img.get("alt") or ""),
                (img.get("title") or ""),
                (img.get("class") and " ".join(img.get("class")) or ""),
                (img.get("id") or ""),
            ]
        ).lower()
        score = 0
        if any(k in attrs for k in ["logo", "brand", "site-logo", "brand-logo", "header-logo", "favicon"]):
            score += 250
        if any(k in (src or "").lower() for k in ["logo", "brand", "icon"]):
            score += 150
        if score:
            add_candidate(src, score)

    if not candidates:
        return None

    # Deduplicate while preserving highest weight
    dedup: dict = {}
    for url, weight in candidates:
        if not url:
            continue
        if url in dedup:
            dedup[url] = max(dedup[url], weight)
        else:
            dedup[url] = weight

    # Sort by weight descending
    sorted_candidates = sorted(dedup.items(), key=lambda x: x[1], reverse=True)

    for img_url, _weight in sorted_candidates:
        img_bytes, ext = download_image(session, img_url)
        if img_bytes:
            return img_bytes, ext
    return None


def convert_image_to_png_if_needed(data: bytes, ext: str) -> Tuple[bytes, str]:
    ext = (ext or "").lower()
    if ext in (".png", ".jpg", ".jpeg"):
        # Normalize .jpeg to .jpg
        if ext == ".jpeg":
            ext = ".jpg"
        return data, ext
    # Attempt conversion via Pillow
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGBA")
            out = io.BytesIO()
            im.save(out, format="PNG")
            return out.getvalue(), ".png"
    except Exception:
        # If conversion fails, return original
        return data, ext or ".img"


def save_image_bytes(out_dir: str, base_name: str, data: bytes, ext: str) -> str:
    ensure_dir(out_dir)
    safe_name = slugify(base_name)
    path = os.path.join(out_dir, f"{safe_name}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def generate_text_logo(property_name: str, size: int = 512) -> bytes:
    img = Image.new("RGB", (size, size), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Try to load a decent TTF font; fall back to default
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font = None
    for p in font_paths:
        if os.path.isfile(p):
            try:
                font = ImageFont.truetype(p, size=64)
                break
            except Exception:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Fit text by reducing font size until it fits within margins
    max_width = int(size * 0.85)
    max_height = int(size * 0.85)
    text = property_name.strip()

    # naive wrap: split to words and assemble lines
    def wrap_text(fnt: ImageFont.FreeTypeFont, text_in: str, max_w: int) -> str:
        words = text_in.split()
        lines: List[str] = []
        cur: List[str] = []
        for w in words:
            test = (" ".join(cur + [w])).strip()
            w_pixels = draw.textlength(test, font=fnt)
            if w_pixels <= max_w:
                cur.append(w)
            else:
                if cur:
                    lines.append(" ".join(cur))
                cur = [w]
        if cur:
            lines.append(" ".join(cur))
        return "\n".join(lines)

    # decrease font size to fit height also
    font_size = 64
    while font_size >= 16:
        try:
            if isinstance(font, ImageFont.FreeTypeFont):
                font = ImageFont.truetype(font.path, size=font_size)
        except Exception:
            pass
        wrapped = wrap_text(font, text, max_width)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=8, align="center")
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= max_width and h <= max_height:
            # center
            x = (size - w) // 2
            y = (size - h) // 2
            draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255), align="center", spacing=8)
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
        font_size -= 4

    # Fallback: just draw at default
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=8, align="center")
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (size - w) // 2
    y = (size - h) // 2
    draw.text((x, y), text, font=font, fill=(255, 255, 255), align="center")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def process_property(
    session: requests.Session,
    row: PropertyRow,
    out_dir: str,
    delay_seconds: float,
) -> ProcessResult:
    base_name = row.property_name or "property"
    notes_parts: List[str] = []

    # 1) Try Instagram discovered from website if website given
    primary_instagram: Optional[str] = None
    if row.website:
        website_url = normalize_url(row.website)
        if website_url:
            ig = find_instagram_on_website(session, website_url)
            if ig:
                primary_instagram = ig
                notes_parts.append("instagram from website")

    # 2) If not found, search Instagram via DuckDuckGo
    if not primary_instagram:
        q_terms = [row.property_name, row.city, row.district, "instagram"]
        query = " ".join([t for t in q_terms if t])
        ig = ddg_search_first_instagram(session, query)
        if ig:
            primary_instagram = ig
            notes_parts.append("instagram from search")
        time.sleep(max(0.1, delay_seconds) + random.uniform(0, 0.5))

    # 3) If Instagram found, attempt to fetch profile image
    if primary_instagram:
        res = extract_instagram_profile_image(session, primary_instagram)
        if res:
            img_bytes, ext = res
            img_bytes, ext2 = convert_image_to_png_if_needed(img_bytes, ext)
            saved_path = save_image_bytes(out_dir, base_name, img_bytes, ext2)
            return ProcessResult(
                status="success",
                source="instagram",
                source_url=primary_instagram,
                saved_path=saved_path,
                notes="; ".join(notes_parts),
            )
        else:
            notes_parts.append("instagram image extraction failed")
        time.sleep(max(0.1, delay_seconds) + random.uniform(0, 0.5))

    # 4) Try extracting a logo from the website (existing or discovered)
    website_to_try = row.website
    if not website_to_try:
        # search for official website
        q_terms = [row.property_name, row.city, row.district, "hotel", "official website"]
        query = " ".join([t for t in q_terms if t])
        try:
            url = ddg_search_first_website(session, query)
            if url:
                website_to_try = url
                notes_parts.append("website from search")
        except Exception:
            website_to_try = None
        time.sleep(max(0.1, delay_seconds) + random.uniform(0, 0.5))

    if website_to_try:
        website_to_try = normalize_url(website_to_try)
        if website_to_try:
            res2 = extract_best_logo_from_website(session, website_to_try)
            if res2:
                img_bytes, ext = res2
                img_bytes, ext2 = convert_image_to_png_if_needed(img_bytes, ext)
                saved_path = save_image_bytes(out_dir, base_name, img_bytes, ext2)
                return ProcessResult(
                    status="success",
                    source="website",
                    source_url=website_to_try,
                    saved_path=saved_path,
                    notes="; ".join(notes_parts),
                )
            else:
                notes_parts.append("website logo extraction failed")

    # 5) Fallback: generate a text-based logo
    fallback_bytes = generate_text_logo(row.property_name)
    saved_path = save_image_bytes(out_dir, base_name, fallback_bytes, ".png")
    return ProcessResult(
        status="fallback",
        source="generated",
        source_url="",
        saved_path=saved_path,
        notes="; ".join(notes_parts) if notes_parts else "no instagram or website found",
    )


def ddg_search_first_website(session: requests.Session, query: str) -> Optional[str]:
    params = {"q": query}
    bad_hosts = [
        "tripadvisor.",
        "booking.com",
        "expedia.",
        "hotels.com",
        "agoda.",
        "airbnb.",
        "kayak.",
        "google.",
        "facebook.com",
        "instagram.com",
        "youtube.com",
        "twitter.com",
        "linkedin.com",
        "wikipedia.org",
    ]
    try:
        resp = session.get(DDG_HTML_SEARCH, params=params)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, DEFAULT_SOUP_PARSER)
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not href:
                continue
            parsed = urlparse(href)
            if parsed.path == "/l/" and "uddg" in parse_qs(parsed.query):
                uddg = parse_qs(parsed.query).get("uddg", [""])[0]
                actual_url = unquote(uddg)
            else:
                actual_url = href
            actual_url = normalize_url(actual_url)
            if not actual_url:
                continue
            host = (urlparse(actual_url).netloc or "").lower()
            if any(b in host for b in bad_hosts):
                continue
            if actual_url.startswith("http"):
                return actual_url
    except Exception:
        return None
    return None


def write_results_csv(path: str, rows: List[Tuple[PropertyRow, ProcessResult]]) -> None:
    ensure_dir(os.path.dirname(path) or ".")
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "property_name",
                "city",
                "district",
                "website",
                "status",
                "source",
                "source_url",
                "saved_path",
                "notes",
            ]
        )
        for pr, res in rows:
            writer.writerow(
                [
                    pr.property_name,
                    pr.city,
                    pr.district,
                    pr.website,
                    res.status,
                    res.source,
                    res.source_url,
                    res.saved_path,
                    res.notes,
                ]
            )


def main():
    parser = argparse.ArgumentParser(description="Generate logos for properties from Instagram or websites.")
    parser.add_argument("--csv", dest="csv_path", default="data/hotels_sample.csv", help="Path to the input CSV file.")
    parser.add_argument("--out", dest="out_dir", default="output_logos", help="Directory to save logos.")
    parser.add_argument("--results", dest="results_csv", default="output_logos/results.csv", help="Path to write results CSV.")
    parser.add_argument("--limit", dest="limit", type=int, default=0, help="Only process the first N rows.")
    parser.add_argument("--delay", dest="delay", type=float, default=1.0, help="Delay seconds between network operations.")
    args = parser.parse_args()

    ensure_dir(args.out_dir)

    try:
        props = read_csv(args.csv_path)
    except Exception as e:
        log_info(f"Failed to read CSV: {e}")
        sys.exit(1)

    if args.limit and args.limit > 0:
        props = props[: args.limit]

    session = create_session()

    results: List[Tuple[PropertyRow, ProcessResult]] = []
    for idx, p in enumerate(props, start=1):
        log_info(f"[{idx}/{len(props)}] Processing: {p.property_name} ({p.city}, {p.district})")
        try:
            res = process_property(session, p, args.out_dir, args.delay)
            log_info(f" -> {res.status} via {res.source}: {res.saved_path}")
        except Exception as e:
            log_info(f" -> error: {e}")
            fb = generate_text_logo(p.property_name)
            saved = save_image_bytes(args.out_dir, p.property_name, fb, ".png")
            res = ProcessResult(
                status="error-fallback",
                source="generated",
                source_url="",
                saved_path=saved,
                notes=str(e),
            )
        results.append((p, res))
        time.sleep(max(0.1, args.delay) + random.uniform(0, 0.5))

    try:
        write_results_csv(args.results_csv, results)
        log_info(f"Results written to: {args.results_csv}")
    except Exception as e:
        log_info(f"Failed to write results CSV: {e}")


if __name__ == "__main__":
    main()