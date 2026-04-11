#!/usr/bin/env python3
"""
Residential IP proxy for slab-cracker.

Fetches PSA cert pages and eBay listing pages from a residential IP
(avoids Cloudflare/anti-bot blocking on cloud IPs).

Usage (local):
    python mcp/psa_proxy.py

Usage (container):
    docker build -t psa-proxy mcp/
    docker run -p 3001:3001 -e PSA_PROXY_API_KEY=mysecret psa-proxy

Environment variables:
    PSA_PROXY_PORT      Port to listen on (default: 3001)
    PSA_PROXY_BIND      Bind address (default: 127.0.0.1, use 0.0.0.0 for container)
    PSA_PROXY_API_KEY   If set, requires X-API-Key header on all requests
"""

import base64
import json
import os
import re
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get("PSA_PROXY_PORT", "3001"))
BIND = os.environ.get("PSA_PROXY_BIND", "127.0.0.1")
API_KEY = os.environ.get("PSA_PROXY_API_KEY", "")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ── PSA page parsing ──────────────────────────────────────────────────────────

CERT_INFO_RE = re.compile(
    r'cert-info-(\d+).*?'
    r'\\?"children\\?":\\?"([^"\\]+)\\?".*?'
    r'\\?"children\\?":\\?"([^"\\]*?)\\?"'
)

# Full-size scan images on CloudFront (handles both escaped and unescaped quotes)
SCAN_IMAGE_RE = re.compile(
    r'\\?"originalPath\\?":\\?"(https://d1htnxwo4o0jhw\.cloudfront\.net/cert/\d+/[a-zA-Z0-9_-]+\.jpg)\\?"'
)


def fetch_url(url: str) -> bytes:
    """Fetch a URL. Uses headless browser for Cloudflare-protected sites (PSA),
    plain curl for everything else (eBay, image downloads)."""
    if "psacard.com" in url:
        return _fetch_browser(url)
    return _fetch_curl(url)


def _fetch_curl(url: str) -> bytes:
    """Plain curl — works for non-Cloudflare sites."""
    result = subprocess.run(
        ["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "20", url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr.decode()[:200]}")
    if not result.stdout:
        raise RuntimeError("curl returned empty response")
    return result.stdout


# Browser singleton — reuse across requests to avoid startup cost
_browser_driver = None

def _get_browser():
    """Get or create a shared browser instance."""
    global _browser_driver
    if _browser_driver is not None:
        try:
            _ = _browser_driver.title  # check if still alive
            return _browser_driver
        except Exception:
            _browser_driver = None

    try:
        import undetected_chromedriver as uc
        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.binary_location = "/usr/bin/chromium"
        _browser_driver = uc.Chrome(options=opts, headless=False)
        print("  Browser started (undetected_chromedriver)")
    except ImportError:
        # Fallback: regular selenium
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.binary_location = "/usr/bin/chromium"
        _browser_driver = webdriver.Chrome(options=opts)
        print("  Browser started (selenium)")
    return _browser_driver


def _fetch_browser(url: str) -> bytes:
    """Fetch a Cloudflare-protected page using a real browser.
    Waits up to 60 seconds for the challenge to clear."""
    import time
    driver = _get_browser()
    driver.get(url)

    # Wait for Cloudflare challenge to clear (up to 60s)
    for i in range(30):
        time.sleep(2)
        title = driver.title or ""
        if "just a moment" not in title.lower():
            break

    page = driver.page_source
    if "just a moment" in (driver.title or "").lower():
        raise RuntimeError("Cloudflare challenge did not clear after 60 seconds")

    return page.encode("utf-8")


def parse_cert_page(html: str) -> dict:
    """Extract cert-info fields from PSA's Next.js RSC payload."""
    fields = {}
    for m in CERT_INFO_RE.finditer(html):
        label = m.group(2)
        value = m.group(3)
        value = value.replace("\\u0026", "&").replace("\\u0027", "'").replace("&#x27;", "'")
        fields[label] = value
    return fields


def parse_scan_urls(html: str) -> list[str]:
    """Extract full-size scan image URLs from the page."""
    return list(dict.fromkeys(m.group(1) for m in SCAN_IMAGE_RE.finditer(html)))


def map_game(category: str, brand: str) -> str:
    b = brand.upper()
    c = category.upper()
    if "POKEMON" in b: return "pokemon"
    if "MAGIC" in b or "MTG" in b: return "mtg"
    if "YU-GI-OH" in b or "YUGIOH" in b: return "yugioh"
    if "ONE PIECE" in b: return "one-piece"
    if "BASEBALL" in c: return "sports-baseball"
    if "BASKETBALL" in c: return "sports-basketball"
    if "FOOTBALL" in c: return "sports-football"
    return "other"


def parse_grade(grade_text: str) -> str:
    """'GEM MT 10' → '10'"""
    parts = grade_text.strip().split()
    return parts[-1] if parts else ""


def parse_set_code(brand: str, game: str) -> str:
    """'POKEMON JTG EN-JOURNEY TOGETHER' → 'jtg'"""
    parts = brand.lower().split()
    if len(parts) < 2:
        return ""
    start = 1 if game == "pokemon" else 1
    if game == "mtg":
        for i, p in enumerate(parts):
            if p == "gathering":
                start = i + 1
                break
    if start >= len(parts):
        return ""
    candidate = parts[start]
    if "-" in candidate:
        candidate = candidate.split("-")[0]
    return candidate


def title_case(s: str) -> str:
    words = s.strip().split()
    result = []
    for w in words:
        if len(w) <= 2 and w == w.lower():
            result.append(w)
        else:
            result.append(w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper())
    return " ".join(result)


def parse_variety(variety: str) -> tuple[str, str]:
    v = variety.upper()
    if not v:
        return "", "base"
    if "SPECIAL ILLUSTRATION RARE" in v: return "special_illustration_rare", "full_art"
    if "ILLUSTRATION RARE" in v: return "illustration_rare", "full_art"
    if "HYPER RARE" in v: return "hyper_rare", "gold"
    if "SECRET RARE" in v: return "secret_rare", "gold"
    if "ULTRA RARE" in v: return "ultra_rare", "full_art"
    if "FULL ART" in v: return "ultra_rare", "full_art"
    if "ALT ART" in v or "ALTERNATE ART" in v: return "ultra_rare", "alt_art"
    if "REVERSE HOLO" in v or "REVERSE FOIL" in v: return "rare", "reverse_holo"
    if "HOLO" in v: return "holo_rare", "holo"
    return variety.lower().replace(" ", "_"), "base"


def lookup_cert(cert_number: str) -> dict:
    """Fetch a PSA cert page, parse metadata, and download scan images."""
    url = f"https://www.psacard.com/cert/{cert_number}"
    html = fetch_url(url).decode("utf-8", errors="replace")

    fields = parse_cert_page(html)
    if not fields:
        return {"error": f"No cert data found for {cert_number} — cert may not exist"}

    brand = fields.get("Brand/Title", "")
    category = fields.get("Category", "")
    game = map_game(category, brand)
    rarity, treatment = parse_variety(fields.get("Variety/Pedigree", ""))

    result = {
        "cert_number": cert_number,
        "game": game,
        "era": fields.get("Year", ""),
        "set_code": parse_set_code(brand, game),
        "card_number": fields.get("Card Number", ""),
        "card_name": title_case(fields.get("Subject", "")),
        "rarity": rarity,
        "treatment": treatment,
        "grading_company": "PSA",
        "grade": parse_grade(fields.get("Item Grade", "")),
        "psa_year": fields.get("Year", ""),
        "psa_brand": brand,
        "psa_subject": fields.get("Subject", ""),
        "psa_category": category,
        "psa_variety": fields.get("Variety/Pedigree", ""),
        "psa_grade_text": fields.get("Item Grade", ""),
    }

    # Download scan images (front, back)
    scan_urls = parse_scan_urls(html)
    scans = []
    for img_url in scan_urls[:2]:  # max 2: front + back
        try:
            img_data = fetch_url(img_url)
            scans.append({
                "url": img_url,
                "data": base64.b64encode(img_data).decode("ascii"),
                "content_type": "image/jpeg",
            })
        except Exception as e:
            print(f"  Warning: failed to download {img_url}: {e}", file=sys.stderr)

    result["scans"] = scans
    result["scan_count"] = len(scans)
    return result


# ── eBay listing scraping ─────────────────────────────────────────────────────

def scrape_ebay_listing(item_id_or_url: str) -> dict:
    """Fetch an eBay listing page and extract photos + metadata."""
    if item_id_or_url.startswith("http"):
        url = item_id_or_url
    else:
        url = f"https://www.ebay.com/itm/{item_id_or_url}"

    html = fetch_url(url).decode("utf-8", errors="replace")
    import html as html_module

    result = {"url": url, "photos": [], "title": "", "price": ""}

    # Parse JSON-LD for structured data
    ld_pattern = re.compile(r'<script\s+type="application/ld\+json">(.*?)</script>', re.DOTALL)
    for m in ld_pattern.finditer(html):
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                data = data[0]
            images = data.get("image", [])
            if isinstance(images, str):
                images = [images]
            for img in images:
                if isinstance(img, dict):
                    img = img.get("url", "")
                if img and "ebayimg.com" in img:
                    img = re.sub(r'/s-l\d+/', '/s-l1600/', img)
                    if img not in result["photos"]:
                        result["photos"].append(img)
            if data.get("name"):
                result["title"] = data["name"]
            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if offers.get("price"):
                result["price"] = f"${offers['price']}"
        except (json.JSONDecodeError, TypeError):
            continue

    # Fallback: og:image
    if not result["photos"]:
        og_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
        if og_match:
            img = re.sub(r'/s-l\d+/', '/s-l1600/', og_match.group(1))
            result["photos"].append(img)

    # Fallback: any ebayimg.com images
    if not result["photos"]:
        for img_match in re.finditer(r'(https://i\.ebayimg\.com/images/g/[^"\'<>\s]+)', html):
            img = re.sub(r'/s-l\d+/', '/s-l1600/', img_match.group(1))
            if img not in result["photos"]:
                result["photos"].append(img)

    # Fallback: title from og:title
    if not result["title"]:
        og_title = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if og_title:
            result["title"] = html_module.unescape(og_title.group(1))

    id_match = re.search(r'/itm/(\d+)', url)
    result["item_id"] = id_match.group(1) if id_match else ""
    result["photo_count"] = len(result["photos"])
    return result


# ── HTTP server ───────────────────────────────────────────────────────────────

class ProxyHandler(BaseHTTPRequestHandler):
    def _check_api_key(self):
        """Returns True if authorized, False if rejected (response already sent)."""
        if not API_KEY:
            return True
        key = self.headers.get("X-API-Key", "")
        if key == API_KEY:
            return True
        self.send_json_error(401, "Invalid or missing X-API-Key")
        return False

    def do_GET(self):
        if not self._check_api_key():
            return

        # Health check
        if self.path == "/health":
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        # Route: /analyze?scan_url=<url>
        if self.path.startswith("/analyze"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            scan_url = qs.get("scan_url", [None])[0]
            if not scan_url:
                self.send_json_error(400, "scan_url query param required")
                return
            print(f"Analyzing centering: {scan_url}")
            try:
                img_data = fetch_url(scan_url)
                from centering import analyze_centering
                result = analyze_centering(img_data)
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                print(f"  -> centering: {result.get('summary', '?')}")
            except Exception as e:
                self.send_json_error(500, f"Analysis failed: {e}")
            return

        # Route: /ebay/{item_id} — scrape eBay listing for photos + metadata
        m_ebay = re.match(r"^/ebay/(\d+)$", self.path)
        if m_ebay:
            item_id = m_ebay.group(1)
            print(f"Scraping eBay listing {item_id}...")
            try:
                result = scrape_ebay_listing(item_id)
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                print(f"  -> {result.get('title', '?')[:60]} | {result.get('photo_count', 0)} photos")
            except Exception as e:
                self.send_json_error(502, str(e))
            return

        # Route: /ebay/photo?url=<photo_url> — download an eBay photo (proxy)
        if self.path.startswith("/ebay/photo"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            photo_url = qs.get("url", [None])[0]
            if not photo_url:
                self.send_json_error(400, "url query param required")
                return
            try:
                img_data = fetch_url(photo_url)
                self.send_response(200)
                self.send_cors_headers()
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(img_data)))
                self.end_headers()
                self.wfile.write(img_data)
            except Exception as e:
                self.send_json_error(502, f"Photo download failed: {e}")
            return

        # Route: /lookup/{cert_number}
        m = re.match(r"^/lookup/(\d+)$", self.path)
        if not m:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"Use /lookup/{cert_number}, /ebay/{item_id}, or /analyze?scan_url=..."}')
            return

        cert_number = m.group(1)
        print(f"Looking up cert {cert_number}...")

        try:
            result = lookup_cert(cert_number)
            body = json.dumps(result).encode("utf-8")
            self.send_response(200)
            self.send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            scan_count = result.get("scan_count", 0)
            print(f"  -> {result.get('card_name', '?')} | {result.get('grade', '?')} | {scan_count} scan(s)")
        except Exception as e:
            self.send_json_error(502, str(e))

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key")

    def send_json_error(self, code, message):
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging
        pass


def main():
    server = HTTPServer((BIND, PORT), ProxyHandler)
    print(f"PSA cert proxy running on http://{BIND}:{PORT}")
    print(f"Usage: http://{BIND}:{PORT}/lookup/133719529")
    if API_KEY:
        print(f"API key required: X-API-Key header")
    else:
        print("No API key configured (set PSA_PROXY_API_KEY for auth)")
    print("Press Ctrl+C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
