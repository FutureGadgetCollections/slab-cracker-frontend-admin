"""
Card centering analysis for PSA scans.

Detects card edges and art edges in a front scan image, measures
left-right border widths at three vertical positions (top, center, bottom),
and produces an annotated preview image for user sign-off.

PSA slab scans are highly consistent — the card edges land at roughly
the same pixel coordinates across all scans. We detect via gradient
but constrain the search to expected zones.
"""

import base64
import io
from PIL import Image, ImageDraw, ImageFont

# ── Constants ────────────────────────────────────────────────────────────────

# Scan lines: fraction of image height where we measure centering
SCAN_POSITIONS = {
    "top": 0.15,     # 15% from top
    "center": 0.50,  # middle
    "bottom": 0.85,  # 85% from top (15% from bottom)
}

# Gradient threshold: minimum brightness change to count as an edge
CARD_EDGE_GRADIENT_THRESHOLD = 40
ART_EDGE_GRADIENT_THRESHOLD = 25

# How many pixels of consistent gradient to confirm an edge (noise filter)
EDGE_CONFIRM_PIXELS = 3

# Expected card edge zone (fraction of image width from each side)
# PSA slabs are consistent — card edge is roughly 10-20% in from image edge
CARD_EDGE_ZONE_MIN = 0.05
CARD_EDGE_ZONE_MAX = 0.30

# Art edge: search inward from card edge, up to this many pixels
ART_EDGE_MAX_SEARCH = 200


# ── Edge detection ───────────────────────────────────────────────────────────

def _pixel_brightness(pixel):
    """Convert an RGB pixel to grayscale brightness."""
    if isinstance(pixel, (int, float)):
        return int(pixel)
    r, g, b = pixel[:3]
    return int(0.299 * r + 0.587 * g + 0.114 * b)


def _find_edge_from_left(img, y, x_start, x_end, threshold, confirm=EDGE_CONFIRM_PIXELS):
    """
    Scan left-to-right along row y from x_start to x_end.
    Returns the x coordinate where a sustained gradient (brightness change)
    exceeds the threshold, or None.
    """
    prev_brightness = _pixel_brightness(img.getpixel((x_start, y)))
    run = 0
    for x in range(x_start + 1, x_end):
        brightness = _pixel_brightness(img.getpixel((x, y)))
        if abs(brightness - prev_brightness) >= threshold:
            run += 1
            if run >= confirm:
                return x - confirm  # return start of the edge
        else:
            run = 0
        prev_brightness = brightness
    return None


def _find_edge_from_right(img, y, x_start, x_end, threshold, confirm=EDGE_CONFIRM_PIXELS):
    """
    Scan right-to-left along row y from x_end to x_start.
    Returns the x coordinate of the edge, or None.
    """
    prev_brightness = _pixel_brightness(img.getpixel((x_end - 1, y)))
    run = 0
    for x in range(x_end - 2, x_start - 1, -1):
        brightness = _pixel_brightness(img.getpixel((x, y)))
        if abs(brightness - prev_brightness) >= threshold:
            run += 1
            if run >= confirm:
                return x + confirm  # return start of the edge
        else:
            run = 0
        prev_brightness = brightness
    return None


def _detect_card_edges(img, y):
    """
    Detect left and right card edges at row y.
    Searches within the expected zone where PSA slab card edges appear.
    """
    w = img.width
    zone_min = int(w * CARD_EDGE_ZONE_MIN)
    zone_max = int(w * CARD_EDGE_ZONE_MAX)

    left = _find_edge_from_left(img, y, zone_min, zone_max, CARD_EDGE_GRADIENT_THRESHOLD)
    right = _find_edge_from_right(img, y, w - zone_max, w - zone_min, CARD_EDGE_GRADIENT_THRESHOLD)

    return left, right


def _detect_art_edges(img, y, card_left, card_right):
    """
    Detect left and right art edges at row y, searching inward from card edges.
    The art edge is where the card border (solid color) transitions to the
    art/content area (variable colors, higher local variance).
    """
    if card_left is None or card_right is None:
        return None, None

    # Search from card_left inward
    search_end = min(card_left + ART_EDGE_MAX_SEARCH, card_right)
    art_left = _find_edge_from_left(
        img, y, card_left + 2, search_end, ART_EDGE_GRADIENT_THRESHOLD
    )

    # Search from card_right inward
    search_start = max(card_right - ART_EDGE_MAX_SEARCH, card_left)
    art_right = _find_edge_from_right(
        img, y, search_start, card_right - 2, ART_EDGE_GRADIENT_THRESHOLD
    )

    return art_left, art_right


# ── Analysis ─────────────────────────────────────────────────────────────────

def analyze_centering(img_bytes: bytes) -> dict:
    """
    Analyze left-right centering of a card front scan.

    Returns a dict with:
      - measurements: per-position edge coordinates and centering ratios
      - annotated_image: base64 PNG with overlay lines
      - summary: overall centering string like "49/51"
    """
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size

    measurements = {}
    for name, frac in SCAN_POSITIONS.items():
        y = int(h * frac)

        card_left, card_right = _detect_card_edges(img, y)
        art_left, art_right = _detect_art_edges(img, y, card_left, card_right)

        left_border = (art_left - card_left) if (art_left and card_left) else None
        right_border = (card_right - art_right) if (card_right and art_right) else None

        total_border = (left_border + right_border) if (left_border and right_border) else None
        if total_border and total_border > 0:
            left_pct = round(left_border / total_border * 100, 1)
            right_pct = round(right_border / total_border * 100, 1)
            ratio = f"{left_pct:.0f}/{right_pct:.0f}"
        else:
            left_pct = right_pct = None
            ratio = "N/A"

        measurements[name] = {
            "y": y,
            "card_edge_left": card_left,
            "card_edge_right": card_right,
            "art_edge_left": art_left,
            "art_edge_right": art_right,
            "left_border_px": left_border,
            "right_border_px": right_border,
            "left_pct": left_pct,
            "right_pct": right_pct,
            "ratio": ratio,
        }

    # Generate annotated preview
    annotated_b64 = _draw_annotated(img, measurements)

    # Overall summary: average ratio
    valid = [m for m in measurements.values() if m["left_pct"] is not None]
    if valid:
        avg_left = sum(m["left_pct"] for m in valid) / len(valid)
        avg_right = sum(m["right_pct"] for m in valid) / len(valid)
        summary = f"{avg_left:.0f}/{avg_right:.0f}"
    else:
        summary = "N/A"

    # Raw image (no annotations) for canvas-based interactive editor
    raw_buf = io.BytesIO()
    img.save(raw_buf, format="PNG", optimize=True)
    raw_b64 = base64.b64encode(raw_buf.getvalue()).decode("ascii")

    return {
        "measurements": measurements,
        "annotated_image": annotated_b64,
        "raw_image": raw_b64,
        "summary": summary,
        "image_width": w,
        "image_height": h,
    }


def _draw_annotated(img: Image.Image, measurements: dict) -> str:
    """Draw edge lines on the image and return as base64 PNG."""
    overlay = img.copy()
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    # Line thickness scales with image size
    thick = max(2, w // 400)
    thin = max(1, thick // 2)

    for name, m in measurements.items():
        y = m["y"]
        # Draw the horizontal scan line (faint)
        draw.line([(0, y), (w, y)], fill=(255, 255, 255, 128), width=thin)

        # Card edges — red
        if m["card_edge_left"] is not None:
            x = m["card_edge_left"]
            draw.line([(x, y - 30), (x, y + 30)], fill=(255, 50, 50), width=thick)
        if m["card_edge_right"] is not None:
            x = m["card_edge_right"]
            draw.line([(x, y - 30), (x, y + 30)], fill=(255, 50, 50), width=thick)

        # Art edges — blue
        if m["art_edge_left"] is not None:
            x = m["art_edge_left"]
            draw.line([(x, y - 30), (x, y + 30)], fill=(50, 100, 255), width=thick)
        if m["art_edge_right"] is not None:
            x = m["art_edge_right"]
            draw.line([(x, y - 30), (x, y + 30)], fill=(50, 100, 255), width=thick)

        # Label with ratio
        label = f"{name}: {m['ratio']}"
        if m["left_border_px"] is not None:
            label += f" ({m['left_border_px']}px / {m['right_border_px']}px)"

        # Position label near the scan line
        label_x = 10
        label_y = y + 35
        # Draw text background
        draw.rectangle(
            [(label_x - 2, label_y - 2), (label_x + len(label) * 10, label_y + 16)],
            fill=(0, 0, 0, 200),
        )
        draw.text((label_x, label_y), label, fill=(255, 255, 255))

    # Legend at the top
    draw.rectangle([(0, 0), (w, 28)], fill=(0, 0, 0, 180))
    draw.text((10, 6), "Red = card edge    Blue = art edge    Approve or adjust below", fill=(255, 255, 255))

    buf = io.BytesIO()
    overlay.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")
