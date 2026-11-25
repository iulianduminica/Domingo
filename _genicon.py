#!/usr/bin/env python3
"""Domingo's mark, drawn with zlib+struct only (no PIL, no network, no fonts).

A sunrise: a gradient sun sitting on a horizon, seven tapered rays fanned
symmetrically above it, three reflection streaks below, over the app's own
aurora wash. Computed per pixel with 3x3 supersampling for smooth edges.
"""
import math, struct, zlib, pathlib

OUT = pathlib.Path(__file__).resolve().parent / "static"
BLACK = (0.0, 0.0, 0.0)
GOLD = (1.0, 0.84, 0.52)        # sun, at the horizon
CORAL = (1.0, 0.42, 0.20)       # sun, at the top
RAY = (1.0, 0.74, 0.28)
AMBER = (1.0, 0.69, 0.18)
INDIGO = (0.10, 0.16, 0.36)     # the cool side of the aurora

SUN_R = 0.190                    # all fractions of the canvas
HORIZON = 0.615                  # sun centre sits on this line
R1, R2 = 0.295, 0.440            # ray band


def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def over(dst, src, alpha):
    return tuple(dst[i] + (src[i] - dst[i]) * alpha for i in range(3))


def clamp01(v):
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def smooth(edge, x):
    """1 at x<=0, 0 at x>=edge, cosine between - cheap analytic anti-aliasing."""
    if x <= 0:
        return 1.0
    if x >= edge:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * (x / edge)))


def inside_rounded(x, y, size, r):
    last = size - 1
    if x < r and y < r:
        return (x - r) ** 2 + (y - r) ** 2 <= r * r
    if x >= size - r and y < r:
        return (x - (last - r)) ** 2 + (y - r) ** 2 <= r * r
    if x < r and y >= size - r:
        return (x - r) ** 2 + (y - (last - r)) ** 2 <= r * r
    if x >= size - r and y >= size - r:
        return (x - (last - r)) ** 2 + (y - (last - r)) ** 2 <= r * r
    return True


def field(px, py, S, bold=False):
    """bold=True is the favicon profile: thicker rays, a bigger sun, no water
       detail - the streaks and the light path turn to mud below ~48 px."""
    col = BLACK
    cx, cy = 0.5 * S, HORIZON * S
    R = SUN_R * S * (1.12 if bold else 1.0)
    horizon = cy
    rw = 1.5 if bold else 1.0

    # ---- aurora wash: warm sky above, cool water below
    for gx, gy, rad, tint, amp in ((0.50 * S, -0.05 * S, 0.62 * S, AMBER, 0.13),
                                   (0.14 * S, 0.10 * S, 0.80 * S, AMBER, 0.20),
                                   (0.92 * S, 0.96 * S, 0.85 * S, INDIGO, 0.95)):
        d = math.hypot(px - gx, py - gy) / rad
        col = over(col, tint, amp * smooth(1.0, d) ** 2)

    # ---- the light the sun throws into the sky, kept tight so it does not go muddy
    d = math.hypot(px - cx, py - cy)
    col = over(col, AMBER, 0.34 * smooth(0.46 * S, d) ** 2.6)

    # ---- rays: seven tapered capsules, symmetric about straight up,
    #          the outer ones a touch shorter so the fan reads as a fan
    for k in range(7):
        ang = math.radians(200 + k * (140 / 6))           # 200..340 deg, mirrored on 270
        off = abs(k - 3) / 3.0                            # 0 at the top, 1 at the edges
        dx, dy = px - cx, py - cy
        ux, uy = math.cos(ang), math.sin(ang)
        along = dx * ux + dy * uy
        perp = abs(-dx * uy + dy * ux)
        r1 = (R1 + 0.012 * off) * S
        r2 = (R2 - 0.030 * off) * S
        t = clamp01((along - r1) / (r2 - r1))
        w = (0.024 - 0.016 * t) * S * rw                  # taper toward the tip
        dist = math.hypot(max(r1 - along, 0.0, along - r2), perp)
        col = over(col, RAY, smooth(w, dist) * (1.0 - 0.40 * t))

    # ---- the sun: a disc clipped at the horizon, one smooth vertical gradient
    if py < horizon:
        a = smooth(0.010 * S, d - R)
        if a > 0:
            v = clamp01((horizon - py) / (R * 1.05))      # 0 at the horizon, 1 at the top
            fill = lerp(GOLD, CORAL, v ** 0.85)
            col = over(col, fill, a)

    # ---- horizon: a crisp lit line, fading at both ends
    span = abs(px - cx) / (0.34 * S)
    col = over(col, GOLD, 0.85 * smooth(0.0045 * S, abs(py - horizon)) * smooth(1.0, span) ** 1.5)

    # ---- the light path on the water: a cone falling from the horizon
    if py > horizon and not bold:
        depth = (py - horizon) / (0.40 * S)
        half = (0.055 + 0.155 * clamp01(depth)) * S
        a = smooth(1.0, abs(px - cx) / half) ** 1.5 * (1.0 - clamp01(depth)) ** 1.4
        col = over(col, AMBER, 0.30 * a)

    # ---- reflection: three streaks, narrower and dimmer as they fall
    if not bold:
        for off, half_w, alpha in ((0.050, 0.150, 0.46), (0.095, 0.105, 0.30), (0.140, 0.065, 0.18)):
            y = horizon + off * S
            a = smooth(0.006 * S, abs(py - y)) * smooth(1.0, abs(px - cx) / (half_w * S)) ** 1.4
            col = over(col, GOLD, alpha * a)

    return col


def png_bytes(size, px):
    raw = b"".join(b"\x00" + b"".join(bytes(v) for v in row) for row in px)

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make(size, path, radius=None, bold=False):
    radius = radius or int(size * 0.235)
    px = []
    for y in range(size):
        row = []
        for x in range(size):
            if not inside_rounded(x, y, size, radius):
                row.append((0, 0, 0, 0))
                continue
            acc = [0.0, 0.0, 0.0]
            n = 0
            for sy in (0.17, 0.5, 0.83):
                for sx in (0.17, 0.5, 0.83):
                    c = field((x + sx) / size, (y + sy) / size, 1.0, bold)
                    acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
                    n += 1
            rgb = tuple(max(0, min(255, round(v / n * 255))) for v in acc)
            row.append(rgb + (255,))          # colour type 6: RGBA
        px.append(row)
    path.write_bytes(png_bytes(size, px))
    print("wrote", path.name, size)


if __name__ == "__main__":
    make(512, OUT / "icon.png")
    make(192, OUT / "icon-192.png")
    make(180, OUT / "apple-touch-icon.png")
    make(32, OUT / "favicon.png", radius=8, bold=True)
