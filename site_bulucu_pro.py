# -*- coding: utf-8 -*-
"""
Site Bulucu (Pro) — Deep Verify + DNS/SSL + Gelişmiş Sosyal + Kalibrasyon
Kullanım örnekleri:
  # 1) Review dosyası üret (Top-3 + kanıt)
  python site_bulucu_pro.py --mode review --input input.csv --output review.xlsx --deep-verify on

  # 2) Review.xlsx'i işaretledikten sonra kalibrasyon modeli eğit
  python site_bulucu_pro.py --calibrate-from review.xlsx

  # 3) Normal koşu (kalibrasyon varsa otomatik kullanır)
  python site_bulucu_pro.py --mode run --input input.csv --output cikti.csv --deep-verify on --prob-threshold 0.65
"""

import argparse, json, pickle, ssl, socket, os
import pandas as pd
import requests, sqlite3, time, random, re, html, difflib
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus
from urllib.error import HTTPError
from typing import List, Dict, Tuple, Optional

# ===== AYARLAR =====
AYARLAR = {
    'PUANLAR': {
        # URL tabanlı
        'ALAN_ADI_NEREDEYSE_AYNI': 15.0,
        'FIRMA_ADI_ALAN_ADINDA': 2.5,
        'UZANTI_COM_TR': 2.0,
        'UZANTI_COM': 1.0,
        'TEMIZ_ALAN_ADI_BONUSU': 1.5,
        'KARISIK_ALAN_ADI_CEZASI': -2.0,
        'NEGATIF_ANAHTAR_KELIME': -12.0,

        # İçerik sinyalleri
        'TITLE_ESES': 6.0,
        'META_ESES': 5.0,
        'H1H2_ESES': 4.0,
        'FOOTER_ESES': 3.0,
        'ICERIKTE_FIRMA_ADI_GECTI': 5.0,

        # Sektör/Şehir/Yapısal
        'SEKTOR_ESLESTI': 10.0,
        'SEKTOR_ESLESMEDI': -20.0,
        'IL_ESLESTI': 4.0,
        'MAIL_DOM_ESLESIR': 4.0,
        'TEL_VAR': 2.0,
        'REDIRECT_SM_CEZASI': -8.0,
        'YASAL_ID_BONUS': 3.0,  # MERSİS/Ver.No/Sicil
        'DNS_VAR_BONUS': 2.0,
        'SSL_CN_BONUS': 3.0,
    },

    'SOSYAL_MEDYA_PUANLARI': {'KULLANICI_ADI_ESLESMESI': 20.0},
    'SOSYAL_MEDYA_PLATFORM_PUANLARI': {
        'instagram': 10, 'facebook': 8, 'youtube': 6, 'linkedin': 5, 'twitter': 3, 'x.com': 3, 'tiktok': 4
    },

    'ARAMA_SORGULARI': [
        "{firma_adi} resmi sitesi", "{firma_adi} {il} iletişim", "{firma_adi}"
    ],
    'SOSYAL_MEDYA_SORGULARI': [
        # site operatörlü + varyantlı
        "site:instagram.com {firma_adi}",
        "site:facebook.com {firma_adi}",
        "site:linkedin.com/company {firma_adi}",
        "site:youtube.com {firma_adi}",
        "site:twitter.com {firma_adi}",
        "site:x.com {firma_adi}",
        "site:tiktok.com {firma_adi}",
        "{firma_adi} instagram", "{firma_adi} facebook", "{firma_adi} linkedin", "{firma_adi} twitter", "{firma_adi} youtube", "{firma_adi} tiktok",
        "{firma_adi} resmi instagram", "{firma_adi} official instagram",
        "{firma_adi} ozel guvenlik instagram", "{firma_adi} ozel guvenlik facebook",
    ],
    'SOSYAL_MEDYA_DOMAINLERI': ["linkedin.com","instagram.com","facebook.com","twitter.com","x.com","youtube.com","t.me","tiktok.com"],
    'TARAYICI_KIMLIKLERI': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    ],

    'SEKTOR_KELIMELERI': [
        "teknoloji","bilişim","yazılım","danışmanlık","güvenlik","koruma","inşaat","gıda","turizm","seyahat","otomotiv",
        "plastik","mobilya","dekorasyon","organizasyon","hukuk","sağlık","eğitim","matbaa","tekstil","lojistik",
        "mühendislik","mimarlık","akademi","denetim","gözetim","medya","telekomünikasyon","belgelendirme","emeklilik",
        "ajans","yapı","çevre","enerji","isg","iş sağlığı","osgb","özel güvenlik","ozel guvenlik"
    ],
    # sektör-özgü sözlükler (pozitif sinyal)
    'SEKTOR_SOZLUK': {
        'ozel_guvenlik': ["5188", "silahli", "silahsız", "yakın koruma", "devriye", "alarm izleme", "güvenlik görevlisi", "site güvenliği"],
        'isg_osgb': ["6331", "osgb", "risk değerlendirmesi", "acil durum", "iş hekimi", "iş güvenliği uzmanı", "toz ölçüm", "ortam ölçümü"],
        'danismanlik_bilisim': ["kvkk", "iso 9001", "penetration test", "sızma testi", "erp", "crm", "sap danışmanlığı"],
    },

    'NEGATIF_KELIMELER': [
        "blog","forum","sikayet","şikayet","sozluk","sözlük","kariyer","ilan","harita","yandex","google","maps",
        "yenifirma","bulurum","firmarehberi","nerede","telefon","find","haber","news","duyuru"
    ],

    'DOGRALANACAK_EN_IYI_ADAY_SAYISI': 4,
    'ISTEK_ZAMAN_ASIMI': 10,

    'CACHE_DB': 'site_finder_cache.sqlite',
    'GOOGLE_RESULTS_PER_QUERY': 6,
    'DUCK_RESULTS_PER_QUERY': 10,

    # Deep verify
    'DEEP_PATHS': ["", "iletisim", "hakkimizda", "en/contact", "tr/iletisim", "about", "contact", "sitemap.xml"],
    'MIN_SINYAL_AUTO_DOMAIN': 2,
    'GECER_MIN_PUAN': 5,

    # Kalibrasyon
    'CALIB_MODEL': 'calibration_model.pkl',
    'CALIB_JSON_FALLBACK': 'calibration_fallback.json',
}

# Şirket eki ve domain yasakları
SIRKET_EKLERI = {
    "ltd","ltd.","limited","ltdsti","ltd.şti","ltd. sti","ltdsti.","ltd şti","ltd.şti.",
    "sti","şti","sti.","şti.","san","sanayi","tic","ticaret","insaat","inşaat","bilisim",
    "bilişim","muhendislik","mühendislik","medya","yazilim","yazılım","danismanlik",
    "danışmanlık","holding","grup","group","anonim","as","a.s.","a.ş.","as.","a.ş"
}
DOMAIN_EK_YASAKLARI = {"ltd","sti","as","anonim","limited","holding","group","grup","sanayi","ticaret"}

# Türkiye yaygın public suffix'ler (minimal PSL)
PUBLIC_SUFFIXES = {
    # TR
    "com.tr","org.tr","net.tr","gen.tr","biz.tr","info.tr","av.tr","dr.tr","pol.tr","bel.tr","k12.tr","edu.tr","gov.tr","tsk.tr","bbs.tr","name.tr","web.tr","tv.tr",
    # Common
    "co.uk","com.br","com.au","co.jp","co.in","co.za","co.id","com.mx","com.ar","com.es"
}

# İller (normalize)
TR_ILLER = [
    "adana","adiyaman","afyonkarahisar","agri","amasya","ankara","antalya","artvin","aydin","balikesir","bilecik",
    "bingol","bitlis","bolu","burdur","bursa","canakkale","cankiri","corum","denizli","diyarbakir","edirne",
    "elazig","erzincan","erzurum","eskisehir","gaziantep","giresun","gumushane","hakkari","hatay","isparta",
    "mersin","istanbul","izmir","kars","kastamonu","kayseri","kirklareli","kirsehir","kocaeli","konya","kutahya",
    "malatya","manisa","kahramanmaras","mardin","mugla","mus","nevsehir","nigde","ordu","rize","sakarya","samsun",
    "siirt","sinop","sivas","tekirdag","tokat","trabzon","tunceli","sanliurfa","usak","van","yozgat","zonguldak",
    "aksaray","bayburt","karaman","kirikkale","batman","sirnak","bartin","ardahan","igdir","yalova","karabuk",
    "kilis","osmaniye","duzce"
]

# Parked/boş sayfa tespiti
PARKING_KALIPLARI = [
    "this domain is for sale", "satilik domain", "satılık domain", "yakinda burada", "yakında burada", "coming soon",
    "nginx default page", "apache2 ubuntu default", "cpanel", "plesk", "index of /",
    "under construction", "site yapim asamasinda", "site yapım aşamasında"
]

# ===== Yardımcılar =====
def metni_normallestir(metin: str) -> str:
    if not isinstance(metin, str): return ""
    metin = metin.lower()
    cevrimler = {'ı':'i','ğ':'g','ü':'u','ş':'s','ö':'o','ç':'c'}
    for e,y in cevrimler.items(): metin = metin.replace(e,y)
    metin = re.sub(r'[^\w\s@\.]', ' ', metin)
    return re.sub(r'\s+', ' ', metin).strip()

def slugify_firma(firma_adi: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', metni_normallestir(firma_adi)).strip('-')

def alan_adini_ayikla(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc.split(':')[0]
    except Exception:
        return ""

def _registrable_domain_parts(domain: str) -> Tuple[str, str]:
    # Dönen: (second_level, suffix)
    # Çok parçalı suffix'leri göz önüne al
    parts = domain.split('.')
    if len(parts) < 2:
        return domain, ''
    # En uzun eşleşen public suffix'i bul
    for i in range(len(parts)-1):
        suffix = '.'.join(parts[i:])
        if suffix in PUBLIC_SUFFIXES:
            second = parts[i-1] if i-1 >= 0 else parts[0]
            return second, suffix
    # Default: son 2 parça
    return parts[-2], parts[-1]

def alan_kok(alan: str) -> str:
    second, _sfx = _registrable_domain_parts(alan)
    return second

def adresten_ili_al(adres: str) -> str:
    if not adres or not isinstance(adres, str): return ""
    norm = metni_normallestir(adres)
    toks = norm.replace(",", " ").split()
    # Metin içinde geçen son şehir adını döndür
    last_city = ""
    for t in toks:
        if t in TR_ILLER:
            last_city = t
    return last_city

def is_social(url: str) -> bool:
    try:
        d = alan_adini_ayikla(url)
        return any(s in d for s in AYARLAR['SOSYAL_MEDYA_DOMAINLERI'])
    except Exception:
        return any(d in url for d in AYARLAR['SOSYAL_MEDYA_DOMAINLERI'])

def headers():
    return {'User-Agent': random.choice(AYARLAR['TARAYICI_KIMLIKLERI'])}

# --- marka çekirdeği ---
def marka_cekirdegi_tokenleri(firma_norm:str) -> List[str]:
    toks = [t for t in firma_norm.split() if t not in SIRKET_EKLERI and len(t) >= 3]
    return toks[:4]

def marka_cekirdegi_bilesik(tokens: List[str]) -> Tuple[str,str]:
    return "".join(tokens), "-".join(tokens)

# Yasal id yakalama
MERSIS_RE = re.compile(r'\b\d{16}\b')
VERGI_RE  = re.compile(r'\b\d{10}\b')
SICIL_RE  = re.compile(r'(sicil|ticaret sicil)\s*no[:\s]*([A-Za-z0-9\-\/]+)', re.I)

def extract_legal_ids(full_text:str):
    mersis = MERSIS_RE.findall(full_text)
    vergi  = VERGI_RE.findall(full_text)
    sicil  = [m[1] for m in SICIL_RE.findall(full_text)]
    return {"mersis": mersis[:1], "vergi": vergi[:1], "sicil": sicil[:1]}

def extract_city_from_text(full_text:str, known_cities:List[str]) -> Optional[str]:
    for city in known_cities:
        if city and city in full_text:
            return city
    return None

def is_parked_page(html_norm: str) -> bool:
    return any(pat in html_norm for pat in PARKING_KALIPLARI)

# ===== DNS & SSL =====
def has_dns_a_record(domain: str, timeout: float = 2.0) -> bool:
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False

def ssl_cn_matches(domain: str, core_tokens: List[str], timeout: float = 3.0) -> bool:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
        subj = cert.get('subject', ())
        texts = []
        for t in subj:
            for k, v in t:
                if isinstance(v, str):
                    texts.append(metni_normallestir(v))
        # SAN alanları
        san = cert.get('subjectAltName', ())
        for typ, val in san:
            if typ.lower() == 'dns' and isinstance(val, str):
                texts.append(metni_normallestir(val))
        cn_text = " ".join(texts)
        join = "".join(core_tokens)
        return bool(join) and (join in cn_text)
    except Exception:
        return False

# ===== Basit SQLite Cache =====
class Cache:
    def __init__(self, path:str):
        self.db = sqlite3.connect(path)
        self._init()
    def _init(self):
        cur = self.db.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS url_cache (url TEXT PRIMARY KEY, html TEXT, ts REAL)")
        cur.execute("CREATE TABLE IF NOT EXISTS query_cache (q TEXT PRIMARY KEY, results TEXT, ts REAL)")
        self.db.commit()
    def get_html(self, url:str) -> Optional[str]:
        cur = self.db.cursor()
        cur.execute("SELECT html FROM url_cache WHERE url=?", (url,))
        row = cur.fetchone()
        return row[0] if row else None
    def set_html(self, url:str, html_text:str):
        cur = self.db.cursor()
        cur.execute("REPLACE INTO url_cache(url, html, ts) VALUES(?,?,?)", (url, html_text, time.time()))
        self.db.commit()
    def get_results(self, q:str) -> Optional[List[str]]:
        cur = self.db.cursor()
        cur.execute("SELECT results FROM query_cache WHERE q=?", (q,))
        row = cur.fetchone()
        if not row: return None
        return row[0].split('\n')
    def set_results(self, q:str, results:List[str]):
        cur = self.db.cursor()
        cur.execute("REPLACE INTO query_cache(q, results, ts) VALUES(?,?,?)", (q, '\n'.join(results), time.time()))
        self.db.commit()

CACHE = Cache(AYARLAR['CACHE_DB'])

# ===== HTTP Session + Retry =====
SESSION = requests.Session()
try:
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    SESSION.mount('http://', adapter)
    SESSION.mount('https://', adapter)
except Exception:
    pass

# ===== HTTP yardımcı =====
def fetch(url:str, timeout:int) -> Optional[str]:
    cached = CACHE.get_html(url)
    if cached is not None:
        return cached
    try:
        r = SESSION.get(url, headers=headers(), timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        html_text = r.text
        if is_social(r.url) and not is_social(url):  # sosyal yönlendirme cezası
            html_text = "<!--REDIRECT_TO_SOCIAL-->" + html_text
        CACHE.set_html(url, html_text)
        return html_text
    except Exception:
        return None

# ===== Arama backendleri =====
def _serpapi_key() -> Optional[str]:
    return os.environ.get('SERPAPI_KEY') or os.environ.get('SERPAPI_API_KEY')

def search_serpapi(query: str, n: int) -> List[str]:
    key = _serpapi_key()
    if not key:
        return []
    try:
        params = {
            'engine': 'google',
            'q': query,
            'hl': 'tr',
            'gl': 'tr',
            'num': max(10, n),
            'api_key': key,
        }
        resp = SESSION.get('https://serpapi.com/search.json', params=params, timeout=AYARLAR['ISTEK_ZAMAN_ASIMI'])
        resp.raise_for_status()
        data = resp.json()
        links = []
        for item in data.get('organic_results', [])[:n]:
            u = item.get('link')
            if u: links.append(u)
        return links
    except Exception:
        return []

def search_google(query:str, n:int) -> List[str]:
    # Önce SerpAPI, yoksa googlesearch, o da olmazsa boş
    res = search_serpapi(query, n)
    if res:
        return res
    try:
        from googlesearch import search as gsearch
        return list(gsearch(query, lang="tr", num_results=n))
    except Exception:
        return []

def search_duckduckgo_html(query:str, n:int) -> List[str]:
    # HTML arayüz + lite fallback
    links = []
    try:
        url = "https://duckduckgo.com/html/?q=" + quote_plus(query)
        r = SESSION.get(url, headers=headers(), timeout=AYARLAR['ISTEK_ZAMAN_ASIMI'])
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.result__a"):
            href = a.get("href")
            if href and href.startswith("http"):
                links.append(href)
            if len(links) >= n: break
    except Exception:
        pass
    if len(links) < n:
        try:
            url = "https://duckduckgo.com/lite/?q=" + quote_plus(query)
            r = SESSION.get(url, headers=headers(), timeout=AYARLAR['ISTEK_ZAMAN_ASIMI'])
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all('a'):
                href = a.get('href')
                if href and href.startswith('http'):
                    links.append(href)
                if len(links) >= n: break
        except Exception:
            pass
    return links[:n]

def run_search(query:str) -> List[str]:
    cached = CACHE.get_results(query)
    if cached is not None: return cached
    results = []
    g = search_google(query, AYARLAR['GOOGLE_RESULTS_PER_QUERY'])
    results.extend(g)
    if len(results) < AYARLAR['GOOGLE_RESULTS_PER_QUERY']:
        results.extend(search_duckduckgo_html(query, AYARLAR['DUCK_RESULTS_PER_QUERY']))
    # uniq + cache
    clean, seen = [], set()
    for u in results:
        if not u: continue
        u = u.strip()
        if u not in seen:
            seen.add(u); clean.append(u)
    CACHE.set_results(query, clean)
    return clean

# ===== Aday domain üretimi =====
def candidate_domains(firma_adi:str) -> List[str]:
    firma_norm = metni_normallestir(firma_adi)
    core_tokens = marka_cekirdegi_tokenleri(firma_norm)
    if not core_tokens:
        toks = [t for t in firma_norm.split() if t not in SIRKET_EKLERI]
        core_tokens = toks[:2] if toks else []
    if not core_tokens:
        return []
    compact, dashed = marka_cekirdegi_bilesik(core_tokens)
    subs = [compact, dashed]
    endings = [".com.tr",".com"]
    cands = []
    for s in subs:
        for e in endings:
            cands.append(f"https://{s}{e}")
            cands.append(f"http://{s}{e}")
    return cands

# ===== İçerik çıkarım =====
def extract_text_signals(html_text:str) -> Dict[str,str]:
    soup = BeautifulSoup(html_text, "html.parser")
    title = (soup.title.string if soup.title else "") or ""
    title = html.unescape(title)
    metas = " ".join([m.get("content","") for m in soup.find_all("meta") if m.get("content")])
    og_site = ""
    og = soup.find("meta", property="og:site_name")
    if og and og.get("content"): og_site = og.get("content")
    htexts = " ".join([h.get_text(" ", strip=True) for h in soup.find_all(['h1','h2'])])
    footer = soup.find("footer")
    ftext = footer.get_text(" ", strip=True) if footer else ""
    full = soup.get_text(" ", strip=True)
    return {
        "title": metni_normallestir(title),
        "metas": metni_normallestir(metas),
        "og": metni_normallestir(og_site),
        "h": metni_normallestir(htexts),
        "footer": metni_normallestir(ftext),
        "full": metni_normallestir(full),
    }

# ===== Sektör sözlüğü sinyali =====
def sektor_lexicon_hits(full_text: str, sektorler: List[str]) -> int:
    text = full_text
    hits = 0
    if any(s in sektorler for s in ["güvenlik","guvenlik","özel güvenlik","ozel guvenlik","koruma"]):
        if any(k in text for k in AYARLAR['SEKTOR_SOZLUK']['ozel_guvenlik']): hits += 1
    if any(s in sektorler for s in ["isg","iş sağlığı","osgb"]):
        if any(k in text for k in AYARLAR['SEKTOR_SOZLUK']['isg_osgb']): hits += 1
    if any(s in sektorler for s in ["bilişim","bilisim","danışmanlık","danismanlik","yazılım","yazilim"]):
        if any(k in text for k in AYARLAR['SEKTOR_SOZLUK']['danismanlik_bilisim']): hits += 1
    return hits

# ===== İçerik sinyali sayacı =====
def content_signal_count(sig: Dict[str,str], url: str, firma_norm: str, sektorler: List[str], il: str) -> int:
    cnt = 0
    if firma_norm and firma_norm in sig['title']: cnt += 1
    if firma_norm and (firma_norm in sig['metas'] or firma_norm in sig['og']): cnt += 1
    if firma_norm and firma_norm in sig['h']: cnt += 1
    if firma_norm and firma_norm in sig['footer']: cnt += 1
    if sektorler and any(sek in sig['full'] for sek in sektorler): cnt += 1
    if il and il in sig['full']: cnt += 1
    mails = re.findall(r'[a-z0-9\._%+-]+@([a-z0-9\.-]+\.[a-z]{2,})', sig['full'])
    alan = alan_adini_ayikla(url)
    if mails and alan and any(alan_kok(m)==alan_kok(alan) for m in mails): cnt += 1
    ids = extract_legal_ids(sig['full'])
    if ids['mersis'] or ids['vergi'] or ids['sicil']: cnt += 1
    if firma_norm and firma_norm in sig['full']: cnt += 1
    # sektör sözlüğü
    cnt += sektor_lexicon_hits(sig['full'], sektorler)
    return cnt

# ===== Skorlama =====
def domain_benzenir_mi(domain_kok:str, core_tokens:List[str]) -> bool:
    core_join = "".join(core_tokens)
    if not core_join or not domain_kok:
        return False
    if domain_kok.startswith(core_join) or core_join in domain_kok:
        return True
    ratio = difflib.SequenceMatcher(None, domain_kok, core_join).ratio()
    return ratio >= 0.82

def quick_url_score(url:str, _firma_kok_eskisi:str, firma_tokens:List[str]) -> float:
    p = AYARLAR['PUANLAR']
    s = 0.0
    alan = alan_adini_ayikla(url)
    if not alan: return -8.0
    akok = alan_kok(alan)

    # domain kökünde şirket eki varsa ağır ceza
    for ban in DOMAIN_EK_YASAKLARI:
        if ban in akok:
            s -= 10.0

    # uzantı puanı
    if alan.endswith(".com.tr"): s += p['UZANTI_COM_TR']
    elif alan.endswith(".com"): s += p['UZANTI_COM']

    # temiz/karmasık
    if '-' in alan or (len(alan.split('.'))>2 and not alan.endswith('.com.tr')):
        s += p['KARISIK_ALAN_ADI_CEZASI']
    else:
        s += p['TEMIZ_ALAN_ADI_BONUSU']

    # negatif kelimeler
    if any(neg in alan for neg in AYARLAR['NEGATIF_KELIMELER']):
        s += p['NEGATIF_ANAHTAR_KELIME']

    # çekirdek marka benzerliği
    core_tokens = marka_cekirdegi_tokenleri(" ".join(firma_tokens))
    if domain_benzenir_mi(akok, core_tokens):
        s += p['ALAN_ADI_NEREDEYSE_AYNI']

    # çekirdek token geçişlerine küçük bonus
    for t in core_tokens:
        if t in alan:
            s += 0.8
    return s

def content_score(url:str, firma_norm:str, sektorler:List[str], il:str, core_tokens:List[str]) -> Tuple[float,int,Dict[str,str]]:
    """dönüş: (puan_artisi, sinyal_say, sig_dict)"""
    p = AYARLAR['PUANLAR']
    html_text = fetch(url, AYARLAR['ISTEK_ZAMAN_ASIMI'])
    if not html_text: return 0.0, 0, {}
    s = 0.0
    if html_text.startswith("<!--REDIRECT_TO_SOCIAL-->"): s += p['REDIRECT_SM_CEZASI']
    sig = extract_text_signals(html_text)

    # Firma adı sinyalleri
    if firma_norm and firma_norm in sig['full']: s += p['ICERIKTE_FIRMA_ADI_GECTI']
    if firma_norm and (firma_norm in sig['title']): s += p['TITLE_ESES']
    if firma_norm and (firma_norm in sig['metas'] or firma_norm in sig['og']): s += p['META_ESES']
    if firma_norm and (firma_norm in sig['h']): s += p['H1H2_ESES']
    if firma_norm and (firma_norm in sig['footer']): s += p['FOOTER_ESES']

    # Sektör
    if sektorler:
        if any(sek in sig['full'] for sek in sektorler): s += p['SEKTOR_ESLESTI']
        else: s += p['SEKTOR_ESLESMEDI']

    # Şehir
    if il and il in sig['full']: s += p['IL_ESLESTI']
    _ = extract_city_from_text(sig['full'], TR_ILLER)

    # Email domaini
    mails = re.findall(r'[a-z0-9\._%+-]+@([a-z0-9\.-]+\.[a-z]{2,})', sig['full'])
    alan = alan_adini_ayikla(url)
    if mails and alan:
        for md in mails:
            if alan_kok(md) == alan_kok(alan):
                s += p['MAIL_DOM_ESLESIR']; break

    # Telefon
    if re.search(r'\b0\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{2}\b', sig['full']) or re.search(r'\+\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{2}', sig['full']):
        s += p['TEL_VAR']

    # Yasal ID
    ids = extract_legal_ids(sig['full'])
    if ids['mersis'] or ids['vergi'] or ids['sicil']:
        s += p['YASAL_ID_BONUS']

    # DNS/SSL
    if has_dns_a_record(alan):
        s += p['DNS_VAR_BONUS']
    if ssl_cn_matches(alan, core_tokens):
        s += p['SSL_CN_BONUS']

    # Sinyal sayımı (+ sektör sözlüğü)
    sinyal = content_signal_count(sig, url, firma_norm, sektorler, il)

    # parked/boş sayfa
    if is_parked_page(sig['full']):
        sinyal = 0

    return s, sinyal, sig

# ===== Deep Verify =====
def deep_verify(base_url: str, firma_norm:str, sektorler:List[str], il:str, core_tokens:List[str]) -> Tuple[int,int]:
    """Birkaç path'i gezip sinyal toplar. return: (toplam_sinyal, sayfa_sayisi)"""
    total = 0
    pages = 0
    for path in AYARLAR['DEEP_PATHS']:
        try:
            if path == "":
                url = base_url
            else:
                url = base_url.rstrip('/') + '/' + path
            html_text = fetch(url, AYARLAR['ISTEK_ZAMAN_ASIMI'])
            if not html_text: continue
            sig = extract_text_signals(html_text)
            s_cnt = content_signal_count(sig, url, firma_norm, sektorler, il)
            total += s_cnt
            pages += 1
        except Exception:
            continue
    return total, pages

# ===== Sosyal medya gelişmiş =====
def _path_parts(u: str):
    try:
        p = urlparse(u).path.strip('/').split('/')
        return [part for part in p if part]
    except Exception:
        return []

def _platform(u: str):
    d = alan_adini_ayikla(u)
    if 'instagram.com' in d: return 'instagram'
    if 'facebook.com'  in d: return 'facebook'
    if 'linkedin.com'  in d: return 'linkedin'
    if 'youtube.com'   in d: return 'youtube'
    if 'tiktok.com'    in d: return 'tiktok'
    if 'twitter.com' in d or 'x.com' in d: return 'twitter'
    return 'other'

def _candidate_handle(u: str):
    plat = _platform(u)
    parts = _path_parts(u)
    if plat == 'instagram':
        return parts[0] if parts else ''
    if plat == 'facebook':
        if parts and parts[0] not in ('profile.php', 'pages'):
            return parts[0]
        return ''
    if plat == 'linkedin':
        if len(parts) >= 2 and parts[0] in ('company','in','school'):
            return parts[1]
        return parts[0] if parts else ''
    if plat == 'youtube':
        if parts and parts[0].startswith('@'):
            return parts[0][1:]
        if len(parts) >= 2 and parts[0] in ('c','user'):
            return parts[1]
        return ''
    if plat == 'twitter':
        return parts[0] if parts else ''
    if plat == 'tiktok':
        return parts[0] if parts else ''
    return ''

def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()

def _core_variants(core_tokens: list[str]) -> list[str]:
    v = set()
    toks = [t for t in core_tokens if len(t) >= 3]
    if not toks: return []
    v.add("".join(toks)); v.add("-".join(toks))
    for i in range(len(toks)):
        v.add(toks[i])
    for i in range(len(toks)-1):
        v.add(toks[i] + toks[i+1])
        v.add(toks[i] + "-" + toks[i+1])
    return [x for x in v if x]

def en_iyi_sosyal_medya_linkini_bul(firma_adi:str, firma_tokens:List[str]) -> str:
    print("      -> Resmi site bulunamadı, sosyal medya aranıyor...")
    aday = set()
    for sablon in AYARLAR['SOSYAL_MEDYA_SORGULARI']:
        q = sablon.format(firma_adi=firma_adi, il="")
        try:
            for u in run_search(q)[:5]:
                if is_social(u): aday.add(u)
        except Exception:
            continue
    if not aday:
        return "Sosyal Medya Hesabı Yok"

    core_tokens = marka_cekirdegi_tokenleri(" ".join(firma_tokens))
    variants = _core_variants(core_tokens) or ["".join(firma_tokens)]

    puanlanmis = []
    for u in aday:
        plat = _platform(u)
        handle = _candidate_handle(u).lower()
        puan = 0.0
        for platform, pval in AYARLAR['SOSYAL_MEDYA_PLATFORM_PUANLARI'].items():
            if platform in u:
                puan += pval; break
        best_sim = 0.0
        for v in variants:
            if not v: continue
            v = v.lower()
            if handle and (v in handle or handle in v):
                best_sim = max(best_sim, 1.0)
            else:
                best_sim = max(best_sim, _name_similarity(handle, v))
        if best_sim >= 0.88:
            puan += AYARLAR['SOSYAL_MEDYA_PUANLARI']['KULLANICI_ADI_ESLESMESI']
        elif best_sim >= 0.76:
            puan += AYARLAR['SOSYAL_MEDYA_PUANLARI']['KULLANICI_ADI_ESLESMESI'] * 0.6
        elif best_sim >= 0.66:
            puan += AYARLAR['SOSYAL_MEDYA_PUANLARI']['KULLANICI_ADI_ESLESMESI'] * 0.4
        puanlanmis.append({'url': u, 'puan': puan})

    puanlanmis.sort(key=lambda x: x['puan'], reverse=True)
    if not puanlanmis:
        return "Sosyal Medya Hesabı Yok"
    best = puanlanmis[0]
    min_accept = 8.0
    if best['puan'] < min_accept:
        return "Sosyal Medya Hesabı Yok"
    return best['url']

# ===== Kalibrasyon: özellik çıkarımı =====
FEATURE_ORDER = [
    "url_ext_comtr","url_ext_com","url_clean","url_neg","url_core_match",
    "cnt_title","cnt_metaog","cnt_h","cnt_footer","cnt_fullname","cnt_sector","cnt_city","cnt_emaildom","cnt_legal","cnt_tel",
    "dns","ssl"
]

def extract_features(url:str, sig:Dict[str,str], url_score:float, firma_norm:str, sektorler:List[str], il:str, core_tokens:List[str]) -> List[float]:
    alan = alan_adini_ayikla(url)
    ext_comtr = 1.0 if alan.endswith(".com.tr") else 0.0
    ext_com   = 1.0 if alan.endswith(".com") else 0.0
    url_clean = 1.0 if ('-' not in alan and (len(alan.split('.'))<=2 or alan.endswith('.com.tr'))) else 0.0
    url_neg   = 1.0 if any(neg in alan for neg in AYARLAR['NEGATIF_KELIMELER']) else 0.0

    akok = alan_kok(alan)
    core_join = "".join(core_tokens)
    core_match = 1.0 if core_join and (akok.startswith(core_join) or core_join in akok or difflib.SequenceMatcher(None, akok, core_join).ratio()>=0.82) else 0.0

    def present(s, frag): return 1.0 if (frag and frag in s) else 0.0
    cnt_title   = present(sig.get('title',''), firma_norm)
    cnt_metaog  = 1.0 if (firma_norm and (firma_norm in sig.get('metas','') or firma_norm in sig.get('og',''))) else 0.0
    cnt_h       = present(sig.get('h',''), firma_norm)
    cnt_footer  = present(sig.get('footer',''), firma_norm)
    cnt_fullname= present(sig.get('full',''), firma_norm)
    cnt_sector  = 1.0 if (sektorler and any(sek in sig.get('full','') for sek in sektorler)) else 0.0
    cnt_city    = present(sig.get('full',''), il)

    mails = re.findall(r'[a-z0-9\._%+-]+@([a-z0-9\.-]+\.[a-z]{2,})', sig.get('full',''))
    cnt_emaildom= 1.0 if (mails and any(alan_kok(m)==alan_kok(alan) for m in mails)) else 0.0

    ids = extract_legal_ids(sig.get('full',''))
    cnt_legal  = 1.0 if (ids['mersis'] or ids['vergi'] or ids['sicil']) else 0.0

    cnt_tel    = 1.0 if (re.search(r'\b0\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{2}\b', sig.get('full','')) or re.search(r'\+\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{2}', sig.get('full',''))) else 0.0

    dns = 1.0 if has_dns_a_record(alan) else 0.0
    sslok = 1.0 if ssl_cn_matches(alan, core_tokens) else 0.0

    feats = [ext_comtr, ext_com, url_clean, url_neg, core_match,
             cnt_title, cnt_metaog, cnt_h, cnt_footer, cnt_fullname, cnt_sector, cnt_city, cnt_emaildom, cnt_legal, cnt_tel,
             dns, sslok]
    return feats

def sigmoid(x):  # fallback için
    import math
    return 1.0/(1.0+math.exp(-x))

def load_calibration():
    try:
        with open(AYARLAR['CALIB_MODEL'],'rb') as f:
            return ('sk', pickle.load(f))
    except Exception:
        try:
            with open(AYARLAR['CALIB_JSON_FALLBACK'],'r',encoding='utf-8') as f:
                data = json.load(f)
            return ('json', data)
        except Exception:
            return (None, None)

def predict_proba_from_feats(feats:List[float], calib_tuple):
    mode, model = calib_tuple
    if not mode: return None
    import numpy as np
    X = np.array(feats, dtype=float).reshape(1,-1)
    if mode == 'sk':
        try:
            return float(model.predict_proba(X)[0,1])
        except Exception:
            return None
    else:
        w = model.get('weights', [0.0]*len(FEATURE_ORDER))
        b = model.get('bias', 0.0)
        z = sum(f*w_i for f, w_i in zip(feats, w)) + b
        return float(sigmoid(z))

# ===== Derin akış =====
def en_iyi_siteyi_bul(firma_adi:str, il:str, norm_firma:str, firma_tokens:List[str], aranan_sektorler:List[str], deep_verify_on:bool, prob_threshold:Optional[float], calib_tuple) -> str:
    # 1) Domain tahmini
    auto_set = set(candidate_domains(firma_adi))
    aday_adresler = set(auto_set)

    # 2) Arama sonuçları
    for sablon in AYARLAR['ARAMA_SORGULARI']:
        q = sablon.format(firma_adi=firma_adi, il=il)
        try:
            for u in run_search(q):
                aday_adresler.add(u)
        except HTTPError:
            time.sleep(15); continue
        except Exception:
            continue
    if not aday_adresler:
        return "Arama Sonucu Yok"

    # 3) URL hızlı puan
    puanlanmis = []
    for url in aday_adresler:
        url_skor = quick_url_score(url, "", firma_tokens)
        puanlanmis.append({'url': url, 'puan': url_skor})

    # 4) İçerik + DeepVerify + Kalibrasyon
    topk = sorted(puanlanmis, key=lambda x: x['puan'], reverse=True)[:AYARLAR['DOGRALANACAK_EN_IYI_ADAY_SAYISI']]
    if not topk:
        return "Arama Sonucu Yok"

    GECER_MIN_PUAN = AYARLAR['GECER_MIN_PUAN']
    MIN_SINYAL = AYARLAR['MIN_SINYAL_AUTO_DOMAIN']
    core_tokens = marka_cekirdegi_tokenleri(norm_firma)
    aday_gecerler = []

    for a in topk:
        html_text = fetch(a['url'], AYARLAR['ISTEK_ZAMAN_ASIMI'])
        sig = {}
        sinyal_say = 0
        if html_text:
            # Parked kontrol
            html_norm = metni_normallestir(html_text)
            if is_parked_page(html_norm):
                a['puan'] = -999; continue

            cs, cscnt, sig = content_score(a['url'], norm_firma, aranan_sektorler, il, core_tokens)
            a['puan'] += cs
            sinyal_say = cscnt
        else:
            # HTML yoksa ve auto domain ise ele
            if a['url'] in auto_set:
                a['puan'] = -999; continue

        # Deep Verify (gerekirse)
        if deep_verify_on and (a['url'] in auto_set or sinyal_say == 0):
            dv_sum, dv_pages = deep_verify(a['url'], norm_firma, aranan_sektorler, il, core_tokens)
            sinyal_say += dv_sum  # sinyalleri topla (sayfa bazlı)
        # Min sinyal şartı (auto domain için)
        if a['url'] in auto_set and sinyal_say < MIN_SINYAL:
            a['puan'] = -999; continue
        # Zayıf olanları ele
        if sinyal_say == 0 and a['puan'] <= GECER_MIN_PUAN:
            a['puan'] = -999; continue

        # Kalibrasyon varsa olasılığa bak
        if calib_tuple[0]:
            feats = extract_features(a['url'], sig or {"title":"","metas":"","og":"","h":"","footer":"","full":""},
                                     a['puan'], norm_firma, aranan_sektorler, il, core_tokens)
            p = predict_proba_from_feats(feats, calib_tuple)
            if p is not None:
                a['proba'] = p
                if prob_threshold is not None and p < prob_threshold:
                    # yeterince emin değil → ele
                    a['puan'] = -999; continue
        aday_gecerler.append(a)

    if not aday_gecerler:
        return "Yeterli Skora Sahip Aday Yok"

    # proba varsa ona göre, yoksa puana göre seç
    winner = max(aday_gecerler, key=lambda x: (x.get('proba', 0.0), x['puan']))
    if winner.get('proba') is None and winner['puan'] <= GECER_MIN_PUAN:
        return "Yeterli Skora Sahip Aday Yok"
    return winner['url']

# --- Top-K aday + kanıt (review modu) ---
def en_iyi_site_adaylari(firma_adi, il, norm_firma, firma_tokens, aranan_sektorler, topk=3, deep_verify_on=True):
    auto_set = set(candidate_domains(firma_adi))
    aday_adresler = set(auto_set)
    for sablon in AYARLAR['ARAMA_SORGULARI']:
        q = sablon.format(firma_adi=firma_adi, il=il)
        try:
            for u in run_search(q):
                aday_adresler.add(u)
        except Exception:
            continue

    puanlanmis = []
    core_tokens = marka_cekirdegi_tokenleri(norm_firma)
    for url in aday_adresler:
        url_skor = quick_url_score(url, "", norm_firma.split())
        html_text = fetch(url, AYARLAR['ISTEK_ZAMAN_ASIMI'])
        kanit = {}
        c_skor = 0.0
        sinyal_say = 0
        if html_text:
            sig = extract_text_signals(html_text)
            flags = []
            if norm_firma and norm_firma in sig['title']: flags.append("title")
            if norm_firma and norm_firma in sig['metas']: flags.append("meta")
            if norm_firma and norm_firma in sig['h']:     flags.append("h1/h2")
            if il and il in sig['full']:                  flags.append(f"il:{il}")
            mails = re.findall(r'[a-z0-9\._%+-]+@([a-z0-9\.-]+\.[a-z]{2,})', sig['full'])
            alan = alan_adini_ayikla(url)
            if mails and alan and any(alan_kok(m)==alan_kok(alan) for m in mails): flags.append("email-domain")
            ids = extract_legal_ids(sig['full'])
            if ids['mersis'] or ids['vergi'] or ids['sicil']: flags.append("yasal-id")
            c_skor, sinyal_say, _ = content_score(url, norm_firma, aranan_sektorler, il, core_tokens)
            if deep_verify_on and (url in auto_set or sinyal_say == 0):
                dv_sum, dv_pages = deep_verify(url, norm_firma, aranan_sektorler, il, core_tokens)
                sinyal_say += dv_sum
                if dv_sum >= AYARLAR['MIN_SINYAL_AUTO_DOMAIN']: flags.append("deep-verify")
            kanit = {"flags": ",".join(flags) if flags else "", "title": sig['title'][:120], "sinyal": sinyal_say}
        toplam = url_skor + c_skor
        puanlanmis.append({"url": url, "puan": toplam, "kanit": kanit})

    top = sorted(puanlanmis, key=lambda x: x['puan'], reverse=True)[:topk]
    return top

def guven_skoru(aday):
    p = aday['puan']
    if p <= 5: return 25
    if p >= 20: return 90
    return int(40 + (p-5)*3)

# ===== Dış arayüz =====
def firma_icin_en_iyi_linki_bul(firma_adi:str, sektor:str="", adres:str="", deep_verify_on=True, prob_threshold:Optional[float]=None, calib_tuple=(None,None)) -> str:
    if not firma_adi: return "Firma Adı Boş"
    norm = metni_normallestir(firma_adi)
    tokens = norm.split()
    il = adresten_ili_al(adres)
    # aranan sektör seti
    aranan = set()
    if sektor:
        for w in metni_normallestir(sektor).split():
            if w: aranan.add(w)
    for w in tokens:
        if w in AYARLAR['SEKTOR_KELIMELERI']: aranan.add(w)
    site = en_iyi_siteyi_bul(firma_adi, il, norm, tokens, list(aranan), deep_verify_on, prob_threshold, calib_tuple)
    if site in ("Arama Sonucu Yok","Yeterli Skora Sahip Aday Yok"):
        sm = en_iyi_sosyal_medya_linkini_bul(firma_adi, tokens)
        return sm
    return site

# ===== Review çıktı =====
def calistir_review_modu(girdi="yenitest.csv", cikti_xlsx="review.xlsx", topk=3, deep_verify_on=True):
    try:
        df = pd.read_csv(girdi, dtype=str)
    except FileNotFoundError:
        print(f"HATA: '{girdi}' bulunamadı."); return
    df.fillna("", inplace=True)
    if "Firma Adı" not in df.columns:
        print("HATA: 'Firma Adı' sütunu yok."); return

    rows = []
    total = len(df)
    for i, row in df.iterrows():
        firma = row.get("Firma Adı","")
        adres = row.get("Adres","")
        sektor = row.get("Sektör","")
        if not firma: continue
        print(f"[{i+1}/{total}] 🏢 {firma}")

        il = adresten_ili_al(adres)
        norm = metni_normallestir(firma)
        tokens = norm.split()
        aranan = set()
        if sektor:
            for w in metni_normallestir(sektor).split():
                if w: aranan.add(w)
        for w in tokens:
            if w in AYARLAR['SEKTOR_KELIMELERI']: aranan.add(w)

        adaylar = en_iyi_site_adaylari(firma, il, norm, tokens, list(aranan), topk=topk, deep_verify_on=deep_verify_on)

        base = {
            "Firma Adı": firma,
            "Adres": adres,
            "Sektör": sektor,
            "Seçilen Doğru URL": "",   # İnsan içi
            "Doğru mu? (1/0)": "",     # İnsan içi
        }
        for idx in range(topk):
            if idx < len(adaylar):
                a = adaylar[idx]
                base[f"Aday{idx+1} URL"] = a['url']
                base[f"Aday{idx+1} Puan"] = round(a['puan'], 2)
                base[f"Aday{idx+1} Kanıt"] = a['kanit'].get("flags","")
                base[f"Aday{idx+1} Başlık"] = a['kanit'].get("title","")
                base[f"Aday{idx+1} Sinyal"] = a['kanit'].get("sinyal","")
            else:
                base[f"Aday{idx+1} URL"] = ""
                base[f"Aday{idx+1} Puan"] = ""
                base[f"Aday{idx+1} Kanıt"] = ""
                base[f"Aday{idx+1} Başlık"] = ""
                base[f"Aday{idx+1} Sinyal"] = ""
        if adaylar:
            eniyi = adaylar[0]
            base["Oto Öneri"] = eniyi['url']
            conf = guven_skoru(eniyi)
            base["Güven (0-100)"] = conf
            base["İnceleme Önceliği"] = "YÜKSEK" if conf < 60 else ("ORTA" if conf < 80 else "DÜŞÜK")
        else:
            base["Oto Öneri"] = ""
            base["Güven (0-100)"] = 0
            base["İnceleme Önceliği"] = "YÜKSEK"

        rows.append(base)
        time.sleep(random.uniform(0.6, 1.2))

    rev = pd.DataFrame(rows)
    try:
        rev.sort_values(by=["İnceleme Önceliği","Güven (0-100)"], ascending=[True, False], inplace=True)
    except Exception:
        pass
    try:
        rev.to_excel(cikti_xlsx, index=False)
    except Exception:
        # openpyxl yoksa csv kaydet
        alt = cikti_xlsx.replace(".xlsx",".csv")
        rev.to_csv(alt, index=False, encoding='utf-8-sig')
        print(f"⚠️ openpyxl yok; review CSV olarak kaydedildi: {alt}")
    print(f"📄 Review çıktısı hazır: {cikti_xlsx}")

# ===== Klasik tam akış =====
def calistir_run_modu(girdi="yenitest.csv", cikti="firma_sonuclari_PRO.csv", deep_verify_on=True, prob_threshold:Optional[float]=None, calib_tuple=(None,None)):
    try:
        df = pd.read_csv(girdi, dtype=str)
    except FileNotFoundError:
        print(f"HATA: '{girdi}' dosyası bulunamadı."); return
    df.fillna("", inplace=True)
    if "Firma Adı" not in df.columns:
        print("HATA: CSV'de 'Firma Adı' yok."); return

    print("Script Çalışıyor...\n")
    out = []
    total = len(df)
    for i, row in df.iterrows():
        firma = row.get("Firma Adı","")
        adres = row.get("Adres","")
        sektor = row.get("Sektör","")
        print(f"[{i+1}/{total}] 🏢 Firma: {firma}")
        link = firma_icin_en_iyi_linki_bul(firma, sektor, adres, deep_verify_on=deep_verify_on, prob_threshold=prob_threshold, calib_tuple=calib_tuple)
        out.append(link)
        print(f"    └──> Sonuç: {link}\n")
        time.sleep(random.uniform(0.8, 1.6))

    df["Bulunan Link"] = out
    df.to_csv(cikti, index=False, encoding='utf-8-sig')
    print(f"✅ İşlem tamamlandı! Sonuçlar '{cikti}' dosyasına yazıldı.")

# ===== Kalibrasyon (review.xlsx -> model) =====
def calibrate_from_review(review_path: str):
    try:
        rev = pd.read_excel(review_path)
    except Exception:
        try:
            rev = pd.read_csv(review_path)
        except Exception as e:
            print(f"HATA: review dosyası okunamadı: {e}")
            return
    needed_cols = ["Firma Adı","Sektör","Doğru mu? (1/0)","Oto Öneri"]
    for c in needed_cols:
        if c not in rev.columns:
            print(f"HATA: review dosyasında '{c}' sütunu yok."); return
    X, y = [], []
    for _, r in rev.iterrows():
        try:
            label = r.get("Doğru mu? (1/0)")
            if label not in (0,1,"0","1"): continue
            label = int(label)
            firma = r.get("Firma Adı","")
            sektor = r.get("Sektör","")
            url = r.get("Seçilen Doğru URL") or r.get("Oto Öneri")
            if not (firma and url): continue
            norm = metni_normallestir(firma)
            tokens = norm.split()
            aranan = set()
            if sektor:
                for w in metni_normallestir(sektor).split():
                    if w: aranan.add(w)
            for w in tokens:
                if w in AYARLAR['SEKTOR_KELIMELERI']: aranan.add(w)
            html_text = fetch(url, AYARLAR['ISTEK_ZAMAN_ASIMI'])
            sig = extract_text_signals(html_text) if html_text else {"title":"","metas":"","og":"","h":"","footer":"","full":""}
            feats = extract_features(url, sig, 0.0, norm, list(aranan), "", marka_cekirdegi_tokenleri(norm))
            X.append(feats); y.append(label)
        except Exception:
            continue
    if not X:
        print("Kalibrasyon için yeterli etiketli veri yok."); return
    # sklearn varsa lojistik; yoksa basit korelasyon temelli ağırlık
    try:
        from sklearn.linear_model import LogisticRegression
        import numpy as np
        model = LogisticRegression(max_iter=1000, solver='lbfgs')
        model.fit(np.array(X), np.array(y))
        with open(AYARLAR['CALIB_MODEL'],'wb') as f:
            pickle.dump(model, f)
        print(f"✅ Kalibrasyon modeli kaydedildi: {AYARLAR['CALIB_MODEL']}")
    except Exception as e:
        # fallback: korelasyon tabanlı ağırlıklar
        import numpy as np
        Xn = np.array(X, dtype=float); yn = np.array(y, dtype=float)
        # z-score normalize ve korelasyon
        Xs = (Xn - Xn.mean(axis=0)) / (Xn.std(axis=0) + 1e-6)
        corr = (Xs.T @ (yn - yn.mean())) / (len(yn)* (yn.std()+1e-6))
        weights = corr.tolist()
        bias = float(-(np.array(weights) @ Xn.mean(axis=0)))
        data = {"weights": weights, "bias": bias, "features": FEATURE_ORDER}
        with open(AYARLAR['CALIB_JSON_FALLBACK'],'w',encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"ℹ️ sklearn bulunamadı; korelasyon temelli kalibrasyon kaydedildi: {AYARLAR['CALIB_JSON_FALLBACK']}")

# ===== CLI =====
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["run","review"], default="run")
    parser.add_argument("--input", default="yenitest.csv")
    parser.add_argument("--output", default="")
    parser.add_argument("--deep-verify", choices=["on","off"], default="on")
    parser.add_argument("--prob-threshold", type=float, default=None, help="Kalibre olasılık eşiği (örn 0.65)")
    parser.add_argument("--calibrate-from", default="", help="review.xlsx yolunu ver; model üretir")
    args = parser.parse_args()

    if args.calibrate_from:
        calibrate_from_review(args.calibrate_from)
        # kalibrasyon sadece yapılır; istersen ardından mode da çalışır
    calib_tuple = load_calibration()

    deep_on = (args.deep_verify == "on")
    if args.mode == "review":
        out = args.output or "review.xlsx"
        calistir_review_modu(args.input, out, topk=3, deep_verify_on=deep_on)
    else:
        out = args.output or "firma_sonuclari_PRO.csv"
        calistir_run_modu(args.input, out, deep_verify_on=deep_on, prob_threshold=args.prob_threshold, calib_tuple=calib_tuple)

if __name__ == "__main__":
    main()