#!/usr/bin/env python3
"""
PSA cert proxy for slab-cracker.

Fetches PSA cert pages from a residential IP (avoids Cloudflare blocking
cloud IPs). Parses metadata and downloads front/back scan images.

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
    """Fetch a URL using curl (bypasses TLS fingerprinting that blocks urllib)."""
    result = subprocess.run(
        ["curl", "-s", "-L", "-A", USER_AGENT, "--max-time", "20", url],
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed (exit {result.returncode}): {result.stderr.decode()[:200]}")
    if not result.stdout:
        raise RuntimeError("curl returned empty response")
    return result.stdout


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

        # Route: /lookup/{cert_number}
        m = re.match(r"^/lookup/(\d+)$", self.path)
        if not m:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b'{"error":"Use /lookup/{cert_number}"}')
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
