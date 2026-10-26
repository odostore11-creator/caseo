import numpy as np, sys, os, re, glob
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter

CW, CH = 906, 1800            # internal canvas
BW, BH = 780, 1638            # body size (100:210)
BX, BY = 63, 40               # body origin
R_BODY = 112
LIGHT = np.array([-0.6, -0.8])  # direction TO the light (image coords, y down)

Y, X = np.mgrid[0:CH, 0:CW].astype(np.float32)


def sdf_rrect(cx, cy, hw, hh, r):
    qx = np.abs(X - cx) - (hw - r)
    qy = np.abs(Y - cy) - (hh - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r


def grad_n(sdf):
    s = gaussian_filter(sdf, 1.2)
    gy, gx = np.gradient(s)
    n = np.hypot(gx, gy) + 1e-6
    return gx / n, gy / n


def lit_of(nx, ny):
    return nx * LIGHT[0] + ny * LIGHT[1]


def smooth(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


import functools
@functools.lru_cache(maxsize=2)
def front(design_path, platform):
    tex = ImageOps.fit(Image.open(design_path).convert('RGB'), (BW, BH), Image.LANCZOS)
    col = np.zeros((CH, CW, 3), np.float32)
    col[BY:BY + BH, BX:BX + BW] = np.asarray(tex, np.float32)
    cx, cy = BX + BW / 2, BY + BH / 2
    sdf = sdf_rrect(cx, cy, BW / 2, BH / 2, R_BODY)
    a_body = np.clip(0.5 - sdf, 0, 1)
    d = np.maximum(-sdf, 0)
    nx, ny = grad_n(sdf)
    lit = lit_of(nx, ny)

    # --- body edge: visible case wall + bevel
    p = np.clip(1 - d / 26, 0, 1) ** 1.5
    col = col * (1 + 0.20 * lit[..., None] * p[..., None]) * (1 - 0.16 * p[..., None])
    wall = np.clip(1 - d / 11, 0, 1)
    wall = smooth(0, 1, wall)
    wall_col = (206 + 38 * lit)[..., None] * np.ones(3, np.float32)
    col = col * (1 - 0.88 * wall[..., None]) + wall_col * 0.88 * wall[..., None]
    spec = np.exp(-((d - 12) / 2.5) ** 2) * np.clip(lit, 0, 1) ** 2
    col += 70 * spec[..., None]
    # raised lip line
    lip = np.exp(-((d - 30) / 2.4) ** 2)
    col *= (1 - 0.13 * lip[..., None])
    col += 28 * (lip * np.clip(lit, 0, 1))[..., None]
    # soft sheen
    sheen = np.exp(-(((X + 0.55 * Y) - 760) / 260) ** 2) * 0.07
    col += 255 * (sheen * (d > 0))[..., None] * 0.6

    alpha = a_body.copy()
    rgb = col

    if platform == 'iphone':
        hx0, hy0, hw, hh = BX + 48, BY + 52, 322, 326
        hcx, hcy = hx0 + hw / 2, hy0 + hh / 2
        sh = sdf_rrect(hcx, hcy, hw / 2, hh / 2, 84)
        hnx, hny = grad_n(sh)
        hlit = lit_of(hnx, hny)
        # raised ring outside hole
        ring_w = 30
        ring = np.clip(1 - sh / ring_w, 0, 1) * (sh > 0)
        rp = smooth(0, 1, ring)
        rgb = rgb * (1 + 0.20 * hlit[..., None] * rp[..., None]) * (1 - 0.0)
        rim = np.exp(-((sh - 5) / 3.0) ** 2) * np.clip(hlit, 0, 1) ** 2
        rgb += 55 * rim[..., None]
        outl = np.exp(-((sh - ring_w) / 2.4) ** 2)
        rgb *= (1 - 0.14 * outl[..., None])
        rgb += 24 * (outl * np.clip(hlit, 0, 1))[..., None]
        # hole interior: wall band then transparent
        inside = np.clip(0.5 - sh, 0, 1)               # 1 in hole
        wall_h = np.clip(1 + sh / 14, 0, 1) * inside   # band inside the hole edge
        wall_h = smooth(0, 1, wall_h)
        inlit = lit_of(-hnx, -hny)
        wc = (196 + 40 * inlit)[..., None] * np.ones(3, np.float32)
        rgb = rgb * (1 - wall_h[..., None]) + wc * wall_h[..., None]
        alpha = alpha * (1 - inside) + a_body * wall_h
        alpha = np.clip(alpha, 0, 1)
    else:
        bx0, by0, bw_, bh_ = BX + 22, BY + 50, BW - 44, 224
        bcx, bcy = bx0 + bw_ / 2, by0 + bh_ / 2
        sh = sdf_rrect(bcx, bcy, bw_ / 2, bh_ / 2, 104)
        hnx, hny = grad_n(sh)
        hlit = lit_of(hnx, hny)
        ring_w = 26
        ring = np.clip(1 - sh / ring_w, 0, 1) * (sh > 0)
        rp = smooth(0, 1, ring)
        rgb = rgb * (1 + 0.20 * hlit[..., None] * rp[..., None])
        rim = np.exp(-((sh - 5) / 3.0) ** 2) * np.clip(hlit, 0, 1) ** 2
        rgb += 55 * rim[..., None]
        outl = np.exp(-((sh - ring_w) / 2.4) ** 2)
        rgb *= (1 - 0.14 * outl[..., None])
        rgb += 24 * (outl * np.clip(hlit, 0, 1))[..., None]
        inside = np.clip(0.5 - sh, 0, 1)
        wall_h = smooth(0, 1, np.clip(1 + sh / 12, 0, 1)) * inside
        inlit = lit_of(-hnx, -hny)
        wc = (190 + 40 * inlit)[..., None] * np.ones(3, np.float32)
        # camera visor (phone part, dark glass)
        vis = np.clip(-sh - 12, 0, 1) * inside
        vis = np.clip((-sh - 11) / 1.5, 0, 1) * inside
        vcol = np.zeros_like(rgb)
        t = np.clip((Y - by0) / bh_, 0, 1)[..., None]
        vcol[:] = (20 + 10 * (1 - t)) * np.ones(3, np.float32)
        vcol[..., 2] += 4
        # glassy top highlight
        vcol += 22 * np.exp(-(((Y - by0) - 20) / 14) ** 2)[..., None] * (inside[..., None])
        # lenses
        lenses = [(bx0 + 108, bcy, 54), (bx0 + 262, bcy, 47), (bx0 + 398, bcy, 38)]
        for (lx, ly, lr) in lenses:
            rr = np.hypot(X - lx, Y - ly)
            ring_m = np.clip((lr + 7 - rr) / 1.5, 0, 1)
            vcol = vcol * (1 - ring_m[..., None]) + np.array([48, 48, 54], np.float32) * ring_m[..., None]
            inner = np.clip((lr - 5 - rr) / 1.5, 0, 1)
            g = np.clip(rr / (lr - 5), 0, 1)
            glass = np.stack([8 + 22 * (1 - g) ** 1.5, 10 + 26 * (1 - g) ** 1.5, 26 + 70 * (1 - g) ** 1.8], -1)
            vcol = vcol * (1 - inner[..., None]) + glass * inner[..., None]
            spx = np.hypot(X - (lx - lr * 0.32), Y - (ly - lr * 0.34))
            vcol += 190 * np.clip((lr * 0.16 - spx) / 2, 0, 1)[..., None]
        for (fx, fy, fr, c) in [(bx0 + bw_ - 130, bcy - 52, 18, (200, 200, 205)), (bx0 + bw_ - 130, bcy + 46, 15, (36, 36, 44))]:
            rr = np.hypot(X - fx, Y - fy)
            m = np.clip((fr - rr) / 1.5, 0, 1)
            vcol = vcol * (1 - m[..., None]) + np.array(c, np.float32) * m[..., None]
        rgb = rgb * (1 - wall_h[..., None]) + wc * wall_h[..., None]
        rgb = rgb * (1 - vis[..., None]) + vcol * vis[..., None]
        alpha = np.clip(alpha, 0, 1)

    rgb = np.clip(rgb, 0, 255)
    return rgb, alpha


def over(bg_rgb, bg_a, fg_rgb, fg_a):
    oa = fg_a + bg_a * (1 - fg_a)
    orgb = (fg_rgb * fg_a[..., None] + bg_rgb * bg_a[..., None] * (1 - fg_a[..., None])) / np.maximum(oa[..., None], 1e-6)
    return orgb, oa


def shadow_layer(sil, dx, dy, s1=24, s2=7, a1=0.36, a2=0.30):
    big = gaussian_filter(np.roll(np.roll(sil, dy, 0), dx, 1), s1) * a1
    tight = gaussian_filter(np.roll(np.roll(sil, int(dy * .3), 0), int(dx * .3), 1), s2) * a2
    inner = gaussian_filter(np.roll(np.roll(sil, 22, 0), 13, 1), 9) * 0.42
    a = 1 - (1 - big) * (1 - tight) * (1 - inner)
    rgb = np.zeros((CH, CW, 3), np.float32) + np.array([24, 20, 18], np.float32)
    return rgb, a


def finish(rgb, a, out_path, size=(604, 1200)):
    arr = np.dstack([np.clip(rgb, 0, 255), np.clip(a, 0, 1) * 255]).astype(np.uint8)
    im = Image.fromarray(arr, 'RGBA').convert('RGBa').resize(size, Image.LANCZOS).convert('RGBA')
    im.save(out_path, 'WEBP', quality=88, alpha_quality=92, method=6)


def render_front(design_path, platform, out_path):
    rgb, a = front(design_path, platform)
    srgb, sa = shadow_layer(a, 16, 30)
    orgb, oa = over(srgb, sa, rgb, a)
    finish(orgb, oa, out_path)


if __name__ == '__main__':
    # Run from the caseo folder:  python make_renders.py
    # Makes render-NN.webp (iPhone) and render-NN-android.webp for every images/design-NN.webp that has none yet.
    folder = sys.argv[1] if len(sys.argv) > 1 else 'images'
    for p in sorted(glob.glob(os.path.join(folder, 'design-*.webp'))):
        m = re.search(r'design-(\d+)\.webp$', p)
        if not m:
            continue
        n = m.group(1)
        for plat, suf in (('iphone', ''), ('android', '-android')):
            out = os.path.join(folder, 'render-%s%s.webp' % (n, suf))
            if os.path.exists(out):
                continue
            render_front(p, plat, out)
            print('made', out, flush=True)
