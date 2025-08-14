#!/usr/bin/env python3
import argparse
import base64
import csv
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from typing import List, Optional, Tuple
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

# Optional: Pillow for PNG output. If not present, we'll emit SVG.
try:
	from PIL import Image, ImageDraw, ImageFont  # type: ignore
	PIL_AVAILABLE = True
except Exception:
	PIL_AVAILABLE = False

CLEARBIT_LOGO_ENDPOINT = "https://logo.clearbit.com/"
DEFAULT_SQUARE_SIZE = 1024
DEFAULT_PADDING_RATIO = 0.08  # 8% padding inside the square


@dataclass
class HotelRecord:
	name: str
	website: Optional[str] = None
	instagram: Optional[str] = None
	city: Optional[str] = None


def safe_mkdir(path: str) -> None:
	os.makedirs(path, exist_ok=True)


def read_hotels_csv(csv_path: str) -> List[HotelRecord]:
	records: List[HotelRecord] = []
	with open(csv_path, newline='', encoding='utf-8') as f:
		reader = csv.DictReader(f)
		for row in reader:
			name = (row.get('name') or row.get('otel') or row.get('otel_adi') or '').strip()
			if not name:
				continue
			website = (row.get('website') or row.get('domain') or row.get('site') or '').strip() or None
			instagram = (row.get('instagram') or row.get('ig') or '').strip() or None
			city = (row.get('city') or row.get('il') or '').strip() or None
			records.append(HotelRecord(name=name, website=website, instagram=instagram, city=city))
	return records


def simple_slugify(text: str) -> str:
	# Normalize and strip accents
	norm = unicodedata.normalize('NFKD', text)
	ascii_text = norm.encode('ascii', 'ignore').decode('ascii')
	ascii_text = ascii_text.lower()
	# Replace non-alphanumeric with dashes
	ascii_text = re.sub(r'[^a-z0-9]+', '-', ascii_text)
	# Trim dashes
	ascii_text = ascii_text.strip('-')
	return ascii_text or 'item'


def normalize_domain(website_or_domain: str) -> Optional[str]:
	if not website_or_domain:
		return None
	website_or_domain = website_or_domain.strip()
	if website_or_domain.startswith(('http://', 'https://')):
		try:
			parsed = urlparse(website_or_domain)
			host = parsed.netloc
		except Exception:
			return None
	else:
		host = website_or_domain
	# Remove path, port
	host = host.split('/')[0]
	host = host.split(':')[0]
	host = re.sub(r'^www\.', '', host, flags=re.IGNORECASE)
	if not host or '.' not in host:
		return None
	return host.lower()


def http_get_bytes(url: str, headers: Optional[dict] = None, timeout: float = 20.0) -> Optional[bytes]:
	try:
		req = Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
		with urlopen(req, timeout=timeout) as resp:
			if resp.status != 200:
				return None
			return resp.read()
	except Exception:
		return None


def try_fetch_logo_from_clearbit_bytes(domain: str, timeout: float = 15.0) -> Optional[bytes]:
	url = CLEARBIT_LOGO_ENDPOINT + domain
	return http_get_bytes(url, timeout=timeout)


def fetch_website_from_bing(query: str, bing_key: Optional[str]) -> Optional[str]:
	if not bing_key:
		return None
	endpoint = "https://api.bing.microsoft.com/v7.0/search"
	try:
		headers = {"Ocp-Apim-Subscription-Key": bing_key, "User-Agent": "Mozilla/5.0"}
		params = {"q": query, "mkt": "tr-TR", "count": 5, "responseFilter": "Webpages"}
		url = endpoint + "?" + urlencode(params)
		req = Request(url, headers=headers)
		with urlopen(req, timeout=20) as resp:
			if resp.status != 200:
				return None
			data = json.loads(resp.read().decode('utf-8', errors='ignore') or '{}')
		web_pages = (data or {}).get('webPages', {}).get('value', [])
		for item in web_pages:
			u = item.get('url')
			if not u:
				continue
			domain = normalize_domain(u)
			if not domain:
				continue
			if any(bad in domain for bad in [
				'booking.com', 'tripadvisor.', 'expedia.', 'hotels.com', 'airbnb.', 'hostelworld.',
				'google.', 'instagram.', 'facebook.', 'twitter.', 'x.com', 'linkedin.', 'youtube.',
				'agoda.', 'trivago.', 'mapy.', 'yandex.', 'wikipedia.', 'wikivoyage.',
			]):
				continue
			return f"https://{domain}"
	except Exception:
		return None
	return None


# ---------- PNG path with Pillow ----------

def ensure_square_image_pil(img: "Image.Image", square_size: int) -> "Image.Image":
	if img.mode != 'RGBA':
		img = img.convert('RGBA')
	width, height = img.size
	scale = min(square_size / width, square_size / height)
	new_w, new_h = int(width * scale), int(height * scale)
	resized = img.resize((new_w, new_h), Image.LANCZOS)
	canvas = Image.new('RGBA', (square_size, square_size), (0, 0, 0, 0))
	offset = ((square_size - new_w) // 2, (square_size - new_h) // 2)
	canvas.paste(resized, offset, resized)
	return canvas


def draw_centered_text_pil(image: "Image.Image", text: str, padding_ratio: float = DEFAULT_PADDING_RATIO) -> "Image.Image":
	draw = ImageDraw.Draw(image)
	width, height = image.size
	padding = int(min(width, height) * padding_ratio)
	text = re.sub(r"\s+", " ", text).strip()
	# Try to fit font
	best_font = None
	if hasattr(ImageFont, 'truetype'):
		# We will try a few common fonts; fallback to default
		font_paths = [
			"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
			"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
		]
		for font_path in font_paths:
			if os.path.exists(font_path):
				low, high = 10, 400
				while low <= high:
					mid = (low + high) // 2
					font = ImageFont.truetype(font_path, mid)
					bbox = draw.multiline_textbbox((0, 0), text, font=font, align='center')
					text_w = bbox[2] - bbox[0]
					text_h = bbox[3] - bbox[1]
					if text_w <= (width - 2 * padding) and text_h <= (height - 2 * padding):
						best_font = font
						low = mid + 2
					else:
						high = mid - 2
				if best_font:
					break
	if best_font is None:
		best_font = ImageFont.load_default()
	bbox = draw.multiline_textbbox((0, 0), text, font=best_font, align='center')
	text_w = bbox[2] - bbox[0]
	text_h = bbox[3] - bbox[1]
	x = (width - text_w) // 2
	y = (height - text_h) // 2
	draw.multiline_text((x, y), text, fill=(255, 255, 255), font=best_font, align='center')
	return image


def generate_placeholder_png(text: str, square_size: int = DEFAULT_SQUARE_SIZE) -> "Image.Image":
	img = Image.new('RGB', (square_size, square_size), (0, 0, 0))
	return draw_centered_text_pil(img, text)


# ---------- SVG path (no Pillow required) ----------

def svg_escape(text: str) -> str:
	return (text.replace('&', '&amp;')
				.replace('<', '&lt;')
				.replace('>', '&gt;'))


def generate_placeholder_svg(text: str, square_size: int = DEFAULT_SQUARE_SIZE) -> str:
	text = re.sub(r"\s+", " ", text).strip()
	pad = int(square_size * DEFAULT_PADDING_RATIO)
	text_length = max(square_size - 2 * pad, 10)
	# Use textLength to ensure it fits horizontally. Center vertically with dominant-baseline.
	svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' width='{square_size}' height='{square_size}' viewBox='0 0 {square_size} {square_size}'>
	<rect x='0' y='0' width='{square_size}' height='{square_size}' fill='black'/>
	<text x='{square_size//2}' y='{square_size//2}' fill='white' font-size='{square_size//10}' font-family='DejaVu Sans, Arial, Helvetica, sans-serif' text-anchor='middle' dominant-baseline='central' lengthAdjust='spacingAndGlyphs' textLength='{text_length}'>
		{svg_escape(text)}
	</text>
</svg>
""".strip()
	return svg


def generate_svg_with_embedded_image(img_bytes: bytes, square_size: int = DEFAULT_SQUARE_SIZE) -> str:
	data_uri = "data:image/png;base64," + base64.b64encode(img_bytes).decode('ascii')
	svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' width='{square_size}' height='{square_size}' viewBox='0 0 {square_size} {square_size}'>
	<defs/>
	<rect x='0' y='0' width='{square_size}' height='{square_size}' fill='none'/>
	<image href='{data_uri}' x='0' y='0' width='{square_size}' height='{square_size}' preserveAspectRatio='xMidYMid meet'/>
</svg>
""".strip()
	return svg


# ---------- Pipeline ----------

def pipeline_for_hotel(record: HotelRecord, outdir: str, square_size: int, bing_key: Optional[str]) -> Tuple[str, str]:
	slug = simple_slugify(record.name)
	use_png = PIL_AVAILABLE
	outfile = os.path.join(outdir, f"{slug}.{'png' if use_png else 'svg'}")

	# Discover domain
	domain = normalize_domain(record.website) if record.website else None
	if not domain and bing_key:
		query_parts = [record.name]
		if record.city:
			query_parts.append(record.city)
		query_parts.append("resmi web sitesi")
		discovered = fetch_website_from_bing(" ".join(query_parts), bing_key)
		domain = normalize_domain(discovered) if discovered else None

	method = ""
	img_bytes = None
	if domain:
		img_bytes = try_fetch_logo_from_clearbit_bytes(domain)
		if img_bytes:
			method = f"clearbit:{domain}"

	if PIL_AVAILABLE:
		if img_bytes:
			try:
				img = Image.open(BytesIO(img_bytes))
				img = ensure_square_image_pil(img, square_size)
				img.save(outfile, format='PNG')
				return outfile, method
			except Exception:
				pass
		# Fallback: placeholder PNG
		img = generate_placeholder_png(record.name, square_size)
		img.save(outfile, format='PNG')
		method = method or "placeholder"
		return outfile, method
	else:
		# SVG path
		if img_bytes:
			svg = generate_svg_with_embedded_image(img_bytes, square_size)
			with open(outfile, 'w', encoding='utf-8') as f:
				f.write(svg)
			return outfile, method
		# Placeholder SVG
		svg = generate_placeholder_svg(record.name, square_size)
		with open(outfile, 'w', encoding='utf-8') as f:
			f.write(svg)
		method = method or "placeholder"
		return outfile, method


def main() -> None:
	parser = argparse.ArgumentParser(description="Hotel logo fetcher with placeholder fallback (PNG if Pillow available, otherwise SVG)")
	parser.add_argument('--input', '-i', required=False, help='Path to CSV with columns: name, website (optional), instagram (optional), city (optional)')
	parser.add_argument('--name', required=False, help='Single hotel name if not using CSV')
	parser.add_argument('--website', required=False, help='Optional website for single hotel')
	parser.add_argument('--city', required=False, help='Optional city for single hotel')
	parser.add_argument('--outdir', '-o', default='logos', help='Output directory for logos')
	parser.add_argument('--size', type=int, default=DEFAULT_SQUARE_SIZE, help='Square output size in pixels')
	parser.add_argument('--bing-key', default=os.environ.get('BING_API_KEY') or os.environ.get('BING_SEARCH_V7_SUBSCRIPTION_KEY'), help='Bing Search API key (optional, used to discover official website)')

	args = parser.parse_args()

	safe_mkdir(args.outdir)

	records: List[HotelRecord] = []
	if args.input:
		records = read_hotels_csv(args.input)
		if not records:
			print(f"[warn] {args.input} boş ya da uygun formatta değil.")
			sys.exit(1)
	else:
		if not args.name:
			print("--input ya da --name sağlamalısınız.")
			sys.exit(1)
		records = [HotelRecord(name=args.name.strip(), website=(args.website or '').strip() or None, city=(args.city or '').strip() or None)]

	print(f"Toplam {len(records)} kayıt işlenecek. Çıktı klasörü: {args.outdir}. Çıktı formatı: {'PNG' if PIL_AVAILABLE else 'SVG'}")

	for rec in records:
		try:
			outfile, method = pipeline_for_hotel(rec, args.outdir, args.size, args.bing_key)
			print(f"✓ {rec.name} -> {outfile} ({method or 'placeholder'})")
		except Exception as exc:
			print(f"✗ {rec.name} hata: {exc}")


if __name__ == '__main__':
	main()