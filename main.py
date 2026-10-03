"""Bomb Clicker — гра на tkinter у стилі Apple.

Клікай по бомбі, щоб подовжити гніт. Що довше протримаєшся — то більший рахунок.
Enter — почати, Space — клік, D — світла/темна тема.

Потрібен Pillow:  pip install pillow
"""
import ctypes
import math
import random
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# ---------------------------------------------------------------- налаштування

W, H = 420, 760          # логічний розмір вікна (масштабується під DPI)
SS = 3                   # суперсемплінг для згладжених фігур

START_FUSE = 100.0
CLICK_BONUS = 2.0        # скільки гноту додає один клік
BASE_BURN = 10.0         # швидкість горіння гноту на старті (% за секунду)
BURN_RAMP = 0.2          # прискорення горіння щосекунди
MAX_BURN = 22.0

BEST_FILE = Path(__file__).with_name("best_score.txt")

# Геометрія макета (логічні пікселі)
PAD = 28
CARD_Y, CARD_H, CARD_GAP, CARD_R = 136, 92, 12, 22
CARD_W = (W - PAD * 2 - CARD_GAP) / 2
CARDS = [(PAD, CARD_Y, PAD + CARD_W, CARD_Y + CARD_H),
         (PAD + CARD_W + CARD_GAP, CARD_Y, W - PAD, CARD_Y + CARD_H)]
RING_CX, RING_CY, RING_R, RING_T = W / 2, 404, 140, 20
BTN_W, BTN_H, BTN_Y = W - PAD * 2, 56, 668

BOMB_SIZE = 200
BODY_C, BODY_R = (100, 116), 58
CORD = ((146.7, 69.3), (152, 36), (174, 30))   # квадратична крива Безьє

THEMES = {
    "light": {
        "bg": "#F5F5F7", "card": "#FFFFFF", "text": "#1D1D1F", "secondary": "#6E6E73",
        "track": "#E8E8ED", "accent": "#0071E3", "accent_hover": "#0077ED",
        "accent_pressed": "#0062C4", "shadow": 22, "dark": False,
    },
    "dark": {
        "bg": "#000000", "card": "#1C1C1E", "text": "#F5F5F7", "secondary": "#98989D",
        "track": "#2C2C2E", "accent": "#0A84FF", "accent_hover": "#409CFF",
        "accent_pressed": "#0071E3", "shadow": 0, "dark": True,
    },
}

GREEN, ORANGE, RED, YELLOW = "#34C759", "#FF9F0A", "#FF3B30", "#FFD60A"


# ---------------------------------------------------------------- утиліти

def hex_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def mix(a, b, t):
    a, b = hex_rgb(a), hex_rgb(b)
    return rgb_hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def ease_out_back(x):
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def fuse_color(f):
    """Колір кільця: зелений → помаранчевий → червоний."""
    if f >= 0.6:
        return GREEN
    if f >= 0.35:
        return mix(ORANGE, GREEN, (f - 0.35) / 0.25)
    if f >= 0.15:
        return mix(RED, ORANGE, (f - 0.15) / 0.2)
    return RED


def bezier(t):
    (x0, y0), (x1, y1), (x2, y2) = CORD
    u = 1 - t
    return (u * u * x0 + 2 * u * t * x1 + t * t * x2,
            u * u * y0 + 2 * u * t * y1 + t * t * y2)


def load_best():
    try:
        return int(BEST_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0


def save_best(value):
    try:
        BEST_FILE.write_text(str(value), encoding="utf-8")
    except OSError:
        pass


def system_prefers_dark():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except Exception:
        return False


# ---------------------------------------------------------------- рендер графіки (Pillow)

def render_background(theme, s):
    k = 2
    u = s * k
    w, h = round(W * s), round(H * s)
    img = Image.new("RGBA", (w * k, h * k), theme["bg"])

    if theme["shadow"]:
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        for x0, y0, x1, y1 in CARDS:
            sd.rounded_rectangle((x0 * u, (y0 + 6) * u, x1 * u, (y1 + 6) * u),
                                 radius=CARD_R * u, fill=(0, 0, 0, theme["shadow"]))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(14 * u)))

    d = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in CARDS:
        d.rounded_rectangle((x0 * u, y0 * u, x1 * u, y1 * u), radius=CARD_R * u, fill=theme["card"])

    r = RING_R
    d.ellipse(((RING_CX - r) * u, (RING_CY - r) * u, (RING_CX + r) * u, (RING_CY + r) * u),
              outline=theme["track"], width=round(RING_T * u))
    return img.resize((w, h), Image.LANCZOS)


def render_arc(fraction, color, s):
    size = round(RING_R * 2 * s)
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    if fraction > 0:
        d = ImageDraw.Draw(img)
        t = RING_T * s * SS
        if fraction >= 0.999:
            d.ellipse((0, 0, big - 1, big - 1), outline=color, width=round(t))
        else:
            start, end = -90, -90 + 360 * fraction
            d.arc((0, 0, big - 1, big - 1), start, end, fill=color, width=round(t))
            rc = big / 2 - t / 2
            for ang in (start, end):  # заокруглені кінці, як у кілець Apple Watch
                a = math.radians(ang)
                x, y = big / 2 + rc * math.cos(a), big / 2 + rc * math.sin(a)
                d.ellipse((x - t / 2, y - t / 2, x + t / 2, y + t / 2), fill=color)
    return img.resize((size, size), Image.LANCZOS)


def render_bomb(cord_frac, s):
    u = s * SS
    size = round(BOMB_SIZE * u)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx, cy = BODY_C

    # м'яка тінь під бомбою
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(((cx - 46) * u, 170 * u, (cx + 46) * u, 184 * u), fill=(0, 0, 0, 90))
    img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(5 * u)))
    d = ImageDraw.Draw(img)

    # корпус з радіальним градієнтом
    hx, hy = 80, 94
    steps = 70
    for i in range(steps):
        t = i / (steps - 1)
        r = BODY_R * (1 - t)
        x, y = cx + (hx - cx) * t, cy + (hy - cy) * t
        col = mix("#141416", "#6C6C72", t ** 1.7)
        d.ellipse(((x - r) * u, (y - r) * u, (x + r) * u, (y + r) * u), fill=col)

    # бліки
    hl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    hd = ImageDraw.Draw(hl)
    hd.ellipse((68 * u, 80 * u, 96 * u, 100 * u), fill=(255, 255, 255, 150))
    hd.ellipse((128 * u, 140 * u, 150 * u, 160 * u), fill=(255, 255, 255, 28))
    img = Image.alpha_composite(img, hl.filter(ImageFilter.GaussianBlur(4 * u)))
    d = ImageDraw.Draw(img)

    # гніт
    pts = [bezier(cord_frac * i / 30) for i in range(31)]
    d.line([(x * u, y * u) for x, y in pts], fill="#C9B79C", width=round(5 * u), joint="curve")
    tx, ty = pts[-1]
    d.ellipse(((tx - 3) * u, (ty - 3) * u, (tx + 3) * u, (ty + 3) * u), fill="#3A3A3C")

    # ковпачок
    dx, dy = math.cos(math.radians(45)), -math.sin(math.radians(45))
    px_, py_ = -dy, dx
    mx, my = cx + 56 * dx, cy + 56 * dy
    hw, hh = 15, 9
    poly = [(mx + sx * hh * dx + sy * hw * px_, my + sx * hh * dy + sy * hw * py_)
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    d.polygon([(x * u, y * u) for x, y in poly], fill="#3A3A3C")
    top = [poly[1], poly[2]]
    d.line([(x * u, y * u) for x, y in top], fill="#5A5A5E", width=round(2 * u))

    return img.resize((round(BOMB_SIZE * s),) * 2, Image.LANCZOS)


def render_spark(seed, s):
    rnd = random.Random(seed)
    u = s * 2
    size = round(48 * u)
    c = size / 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    def blob(r, color, blur):
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse((c - r * u, c - r * u, c + r * u, c + r * u), fill=color)
        return layer.filter(ImageFilter.GaussianBlur(blur * u)) if blur else layer

    img = Image.alpha_composite(img, blob(rnd.uniform(13, 17), (255, 149, 0, 120), 5))
    img = Image.alpha_composite(img, blob(rnd.uniform(6, 8), (255, 214, 10, 230), 2))
    img = Image.alpha_composite(img, blob(rnd.uniform(2.5, 3.5), (255, 255, 240, 255), 0.6))
    return img.resize((round(48 * s),) * 2, Image.LANCZOS)


def render_burst(s):
    rnd = random.Random(7)
    u = s * 2
    size = round(250 * u)
    c = size / 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((c - 100 * u, c - 100 * u, c + 100 * u, c + 100 * u),
                                 fill=(255, 159, 10, 110))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(14 * u)))
    d = ImageDraw.Draw(img)

    def star(n, outer, inner, color):
        pts = []
        for i in range(n * 2):
            a = i * math.pi / n - math.pi / 2
            r = (outer if i % 2 == 0 else inner) * rnd.uniform(0.86, 1.06)
            pts.append((c + r * u * math.cos(a), c + r * u * math.sin(a)))
        d.polygon(pts, fill=color)

    star(14, 112, 74, "#FF9F0A")
    star(12, 80, 50, YELLOW)
    d.ellipse((c - 34 * u, c - 34 * u, c + 34 * u, c + 34 * u), fill="#FFF6D5")
    return img.resize((round(250 * s),) * 2, Image.LANCZOS)


def render_pill(color, s):
    u = s * SS
    img = Image.new("RGBA", (round(BTN_W * u), round(BTN_H * u)), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, img.width - 1, img.height - 1),
                                          radius=BTN_H / 2 * u, fill=color)
    return img.resize((round(BTN_W * s), round(BTN_H * s)), Image.LANCZOS)


# ---------------------------------------------------------------- гра

class BombClicker:
    def __init__(self, root):
        self.root = root
        self.s = root.winfo_fpixels("1i") / 96
        self.theme_name = "dark" if system_prefers_dark() else "light"

        self._init_fonts()
        self._init_window()

        self.cache = {}
        self.pil_cache = {}
        self.new_record = False
        self.best = load_best()
        self.state = "idle"            # idle | playing | over
        self.fuse = START_FUSE
        self.shown_fuse = START_FUSE
        self.elapsed = 0.0
        self.score = 0
        self.pulse = 0.0
        self.burst_t = 0.0
        self.shake = 0.0
        self.offset = (0, 0)
        self.particles = []
        self.floaters = []
        self.btn_hover = self.btn_down = False
        self.space_down = False
        self.last_values = {}

        self._build_items()
        self.apply_theme()
        self._bind()
        self.set_state_ui()

        self.warmup = self._warmup_jobs()
        self.root.after(50, self._run_warmup)
        self.last_t = time.perf_counter()
        self.loop()

    # ---- налаштування вікна та шрифтів

    def px(self, v):
        return round(v * self.s)

    def _init_fonts(self):
        fams = set(tkfont.families())

        def pick(*names):
            return next((n for n in names if n in fams), "TkDefaultFont")

        display = pick("SF Pro Display", "Segoe UI Variable Display", "Segoe UI")
        display_sb = pick("SF Pro Display Semibold", "Segoe UI Variable Display Semib", "Segoe UI Semibold")
        text = pick("SF Pro Text", "Segoe UI Variable Text", "Segoe UI")
        text_sb = pick("SF Pro Text Semibold", "Segoe UI Variable Text Semibold", "Segoe UI Semibold")
        p = self.px
        self.f_title = (display, -p(34), "bold")
        self.f_sub = (text, -p(15))
        self.f_caption = (text_sb, -p(12))
        self.f_value = (display_sb, -p(34))
        self.f_fuse = (display_sb, -p(30))
        self.f_button = (text_sb, -p(17))
        self.f_hint = (text, -p(12))
        self.f_float = (display_sb, -p(20))

    def _init_window(self):
        r = self.root
        r.title("Bomb Clicker")
        r.resizable(False, False)
        w, h = self.px(W), self.px(H)
        x = (r.winfo_screenwidth() - w) // 2
        y = max(0, (r.winfo_screenheight() - h) // 2 - self.px(20))
        r.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas = tk.Canvas(r, width=w, height=h, highlightthickness=0, bd=0)
        self.canvas.pack()

    def _style_titlebar(self):
        """Windows 11: темний/світлий заголовок вікна в колір фону."""
        if sys.platform != "win32":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            dwm = ctypes.windll.dwmapi
            dark = ctypes.c_int(1 if self.t["dark"] else 0)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
            r, g, b = hex_rgb(self.t["bg"])
            color = ctypes.c_int(r | (g << 8) | (b << 16))
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)
        except Exception:
            pass

    # ---- кеш зображень

    def img(self, key, factory):
        if key not in self.cache:
            self.cache[key] = ImageTk.PhotoImage(factory())
        return self.cache[key]

    def arc_img(self, value):
        f = value / 100
        return self.img(("arc", value), lambda: render_arc(f, fuse_color(f), self.s))

    def pil(self, key, factory):
        if key not in self.pil_cache:
            self.pil_cache[key] = factory()
        return self.pil_cache[key]

    def bomb_img(self, bucket, scale):
        def scaled():
            src = self.pil(("bomb", bucket), lambda: render_bomb(bucket, self.s))
            n = round(BOMB_SIZE * self.s * scale)
            return src if scale == 1 else src.resize((n, n), Image.LANCZOS)
        return self.img(("bomb", bucket, scale), scaled)

    def spark_img(self, seed):
        return self.img(("spark", seed), lambda: render_spark(seed, self.s))

    def burst_img(self, scale):
        def scaled():
            src = self.pil("burst", lambda: render_burst(self.s))
            n = max(1, round(250 * self.s * scale))
            return src.resize((n, n), Image.LANCZOS)
        return self.img(("burst", scale), scaled)

    def _warmup_jobs(self):
        for v in range(100, -1, -1):
            yield lambda v=v: self.arc_img(v)
        for b in range(16, 0, -1):
            for sc in (1, 0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.93):
                yield lambda b=b, sc=sc: self.bomb_img(b / 16, sc)
        for seed in range(6):
            yield lambda seed=seed: self.spark_img(seed)
        for i in range(1, 23):
            yield lambda i=i: self.burst_img(round(i * 0.05, 2))

    def _run_warmup(self):
        start = time.perf_counter()
        for job in self.warmup:
            job()
            if time.perf_counter() - start > 0.008:
                self.root.after(12, self._run_warmup)
                return

    # ---- елементи інтерфейсу

    def _build_items(self):
        c, p = self.canvas, self.px
        self.i_bg = c.create_image(0, 0, anchor="nw")
        self.i_title = c.create_text(p(PAD), p(66), anchor="w", text="Bomb Clicker", font=self.f_title)
        self.i_sub = c.create_text(p(PAD), p(102), anchor="w", font=self.f_sub)

        self.i_card_labels, self.i_card_values = [], []
        for (x0, y0, _, _), label in zip(CARDS, ("РАХУНОК", "РЕКОРД")):
            self.i_card_labels.append(
                c.create_text(p(x0 + 20), p(y0 + 26), anchor="w", text=label, font=self.f_caption))
            self.i_card_values.append(
                c.create_text(p(x0 + 20), p(y0 + 60), anchor="w", text="0", font=self.f_value))

        self.i_arc = c.create_image(p(RING_CX), p(RING_CY))
        self.i_burst = c.create_image(p(RING_CX), p(RING_CY), state="hidden")
        self.i_bomb = c.create_image(p(RING_CX), p(RING_CY), tags=("bomb",))
        self.i_spark = c.create_image(0, 0)

        self.i_fuse_cap = c.create_text(p(RING_CX), p(574), text="ГНІТ", font=self.f_caption)
        self.i_fuse = c.create_text(p(RING_CX), p(604), text="100%", font=self.f_fuse)

        self.i_btn = c.create_image(p(W / 2), p(BTN_Y), tags=("btn",))
        self.i_btn_text = c.create_text(p(W / 2), p(BTN_Y), fill="#FFFFFF", font=self.f_button, tags=("btn",))
        self.i_hint = c.create_text(p(W / 2), p(728), font=self.f_hint,
                                    text="Enter — почати   ·   Space — клік   ·   D — тема")

    def apply_theme(self):
        self.t = t = THEMES[self.theme_name]
        c = self.canvas
        c.configure(bg=t["bg"])
        c.itemconfig(self.i_bg, image=self.img(("bg", self.theme_name), lambda: render_background(t, self.s)))
        for name in ("accent", "accent_hover", "accent_pressed"):
            self.img(("pill", self.theme_name, name), lambda n=name: render_pill(t[n], self.s))
        c.itemconfig(self.i_title, fill=t["text"])
        c.itemconfig(self.i_hint, fill=t["secondary"])
        c.itemconfig(self.i_fuse_cap, fill=t["secondary"])
        for item in self.i_card_labels:
            c.itemconfig(item, fill=t["secondary"])
        for item in self.i_card_values:
            c.itemconfig(item, fill=t["text"])
        self.last_values.pop("sub", None)
        self.update_button()
        self._style_titlebar()

    def toggle_theme(self, _event=None):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.apply_theme()

    def update_button(self):
        key = "accent_pressed" if self.btn_down else "accent_hover" if self.btn_hover else "accent"
        self.canvas.itemconfig(self.i_btn, image=self.cache[("pill", self.theme_name, key)])

    def set_text(self, item, key, text, fill=None):
        """Оновлює текст лише коли він справді змінився."""
        if self.last_values.get(key) != (text, fill):
            self.last_values[key] = (text, fill)
            self.canvas.itemconfig(item, text=text, **({"fill": fill} if fill else {}))

    def set_state_ui(self):
        label = {"idle": "Почати гру", "playing": "Клік!", "over": "Грати ще"}[self.state]
        self.canvas.itemconfig(self.i_btn_text, text=label)
        self.canvas.itemconfig(self.i_card_values[1], text=str(self.best))

    # ---- керування

    def _bind(self):
        c, r = self.canvas, self.root
        c.tag_bind("btn", "<Enter>", lambda e: self._btn_hover(True))
        c.tag_bind("btn", "<Leave>", lambda e: self._btn_hover(False))
        c.tag_bind("btn", "<ButtonPress-1>", self._btn_press)
        c.tag_bind("btn", "<ButtonRelease-1>", self._btn_release)
        c.tag_bind("bomb", "<ButtonPress-1>", lambda e: self.click())
        c.tag_bind("bomb", "<Enter>", lambda e: c.configure(cursor="hand2"))
        c.tag_bind("bomb", "<Leave>", lambda e: c.configure(cursor=""))
        r.bind("<Return>", lambda e: self.start())
        r.bind("<KP_Enter>", lambda e: self.start())
        r.bind("<KeyPress-space>", self._space_press)
        r.bind("<KeyRelease-space>", lambda e: setattr(self, "space_down", False))
        r.bind("<KeyPress-d>", self.toggle_theme)
        r.bind("<KeyPress-D>", self.toggle_theme)

    def _btn_hover(self, on):
        self.btn_hover = on
        if not on:
            self.btn_down = False
        self.canvas.configure(cursor="hand2" if on else "")
        self.update_button()

    def _btn_press(self, _e):
        self.btn_down = True
        self.update_button()
        if self.state == "playing":   # під час гри кнопка — це ще один клік по бомбі
            self.click()

    def _btn_release(self, _e):
        was_down = self.btn_down
        self.btn_down = False
        self.update_button()
        if was_down and self.state != "playing":
            self.start()

    def _space_press(self, _e):
        if self.space_down:           # ігноруємо автоповтор затиснутої клавіші
            return
        self.space_down = True
        if self.state == "playing":
            self.click()
        else:
            self.start()

    # ---- ігрова логіка

    def start(self):
        if self.state == "playing":
            return
        self.state = "playing"
        self.fuse = self.shown_fuse = START_FUSE
        self.elapsed = 0.0
        self.score = 0
        self.burst_t = 0.0
        self.canvas.itemconfig(self.i_burst, state="hidden")
        self.canvas.itemconfig(self.i_bomb, state="normal")
        self.canvas.itemconfig(self.i_spark, state="normal")
        self.set_state_ui()

    def click(self):
        if self.state != "playing":
            return
        self.fuse = min(START_FUSE, self.fuse + CLICK_BONUS)
        self.pulse = 1.0
        self._spawn_floater()

    def explode(self):
        self.fuse = 0
        self.state = "over"
        self.new_record = self.score > self.best
        if self.new_record:
            self.best = self.score
            save_best(self.best)
        self.canvas.itemconfig(self.i_bomb, state="hidden")
        self.canvas.itemconfig(self.i_spark, state="hidden")
        self.canvas.itemconfig(self.i_burst, state="normal")
        self.shake = 0.45
        cx, cy = RING_CX, RING_CY + 16
        for _ in range(44):
            a = random.uniform(0, math.tau)
            v = random.uniform(140, 440)
            self._spawn_particle(cx, cy, v * math.cos(a), v * math.sin(a) - 120,
                                 random.choice((ORANGE, YELLOW, RED, "#FF6B00", "#8E8E93")),
                                 random.uniform(2.5, 6.5), random.uniform(0.6, 1.2))
        self.set_state_ui()

    def update(self, dt):
        if self.state != "playing":
            return
        self.elapsed += dt
        burn = min(MAX_BURN, BASE_BURN + BURN_RAMP * self.elapsed)
        self.fuse -= burn * dt
        self.score = int(self.elapsed)
        if self.fuse <= 0:
            self.explode()

    # ---- частинки та спливаючий текст

    def _spawn_particle(self, x, y, vx, vy, color, r, life, gravity=520):
        item = self.canvas.create_oval(0, 0, 0, 0, fill=color, outline="")
        self.particles.append({"item": item, "x": x, "y": y, "vx": vx, "vy": vy, "r": r,
                               "color": color, "life": life, "max": life, "g": gravity})

    def _spawn_floater(self):
        p = self.px
        x = RING_CX + random.uniform(-60, 60)
        y = RING_CY - 40 + random.uniform(-20, 20)
        item = self.canvas.create_text(p(x) + self.offset[0], p(y) + self.offset[1],
                                       text=f"+{CLICK_BONUS:g}", font=self.f_float, fill=self.t["accent"])
        self.floaters.append({"item": item, "t": 0.0})

    def _update_effects(self, dt):
        c, p, bg = self.canvas, self.px, self.t["bg"]
        ox, oy = self.offset
        alive = []
        for pt in self.particles:
            pt["life"] -= dt
            if pt["life"] <= 0:
                c.delete(pt["item"])
                continue
            pt["vy"] += pt["g"] * dt
            pt["x"] += pt["vx"] * dt
            pt["y"] += pt["vy"] * dt
            k = pt["life"] / pt["max"]
            r = pt["r"] * (0.4 + 0.6 * k)
            x, y = p(pt["x"]) + ox, p(pt["y"]) + oy
            c.coords(pt["item"], x - p(r), y - p(r), x + p(r), y + p(r))
            c.itemconfig(pt["item"], fill=mix(pt["color"], bg, 1 - k))
            alive.append(pt)
        self.particles = alive

        alive = []
        for fl in self.floaters:
            fl["t"] += dt / 0.65
            if fl["t"] >= 1:
                c.delete(fl["item"])
                continue
            c.move(fl["item"], 0, -p(70) * dt)
            c.itemconfig(fl["item"], fill=mix(self.t["accent"], bg, fl["t"] ** 2))
            alive.append(fl)
        self.floaters = alive

    # ---- головний цикл анімації (~60 fps)

    def loop(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.last_t)
        self.last_t = now

        self.update(dt)
        self._render(dt)
        self.root.after(16, self.loop)

    def _render(self, dt):
        c, p, t = self.canvas, self.px, self.t

        # тремтіння екрана після вибуху
        if self.shake > 0:
            self.shake = max(0.0, self.shake - dt)
            amp = 9 * self.s * (self.shake / 0.45)
            new = (round(random.uniform(-amp, amp)), round(random.uniform(-amp, amp)))
        else:
            new = (0, 0)
        if new != self.offset:
            c.move("all", new[0] - self.offset[0], new[1] - self.offset[1])
            self.offset = new
        ox, oy = self.offset

        # кільце-гніт
        self.shown_fuse += (self.fuse - self.shown_fuse) * min(1.0, dt * 14)
        ring_value = int(round(clamp(self.shown_fuse, 0, 100)))
        if self.last_values.get("arc") != ring_value:
            self.last_values["arc"] = ring_value
            c.itemconfig(self.i_arc, image=self.arc_img(ring_value))
        f = clamp(self.fuse / 100)
        self.set_text(self.i_fuse, "fuse", f"{math.ceil(max(0.0, self.fuse))}%", fuse_color(f))

        # бомба та іскра
        if self.state != "over":
            self.pulse *= math.exp(-dt * 12)
            scale = round(1 - 0.07 * self.pulse, 2)
            bucket = max(1, round((0.1 + 0.9 * f) * 16)) / 16
            c.itemconfig(self.i_bomb, image=self.bomb_img(bucket, scale))
            jx = jy = 0.0
            if self.state == "playing" and f < 0.25:
                amp = 1.6 * (1 - f / 0.25)
                jx, jy = random.uniform(-amp, amp), random.uniform(-amp, amp)
            bx, by = RING_CX + jx, RING_CY + jy
            c.coords(self.i_bomb, p(bx) + ox, p(by) + oy)

            tx, ty = bezier(bucket)
            sx = bx + (tx - BOMB_SIZE / 2) * scale
            sy = by + (ty - BOMB_SIZE / 2) * scale
            c.coords(self.i_spark, p(sx) + ox, p(sy) + oy)
            c.itemconfig(self.i_spark, image=self.spark_img(random.randrange(6)))
            if random.random() < (0.55 if self.state == "playing" else 0.25):
                a = random.uniform(-math.pi, 0)
                v = random.uniform(30, 110)
                self._spawn_particle(sx, sy, v * math.cos(a), v * math.sin(a),
                                     random.choice((YELLOW, ORANGE, "#FFF6D5")),
                                     random.uniform(1, 2), random.uniform(0.25, 0.5), gravity=180)
        elif self.burst_t < 0.4:
            self.burst_t += dt
            k = ease_out_back(clamp(self.burst_t / 0.4))
            c.itemconfig(self.i_burst, image=self.burst_img(round(clamp(k, 0.05, 1.1) * 20) / 20))

        self._update_effects(dt)

        # тексти
        self.set_text(self.i_card_values[0], "score", str(self.score))
        if self.state == "idle":
            sub, col = "Натисни «Почати гру» або Enter", t["secondary"]
        elif self.state == "playing":
            if f < 0.25:
                sub, col = "Швидше! Гніт догорає", RED
            else:
                sub, col = "Клікай по бомбі, щоб подовжити гніт", t["secondary"]
        elif self.new_record:
            sub, col = f"Новий рекорд — {self.score} с!", GREEN
        else:
            sub, col = f"Бум! Ти протримався {self.score} с", t["secondary"]
        self.set_text(self.i_sub, "sub", sub, col)


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # чіткий рендер на HiDPI-екранах
        except Exception:
            pass
    root = tk.Tk()
    app = BombClicker(root)
    icon = ImageTk.PhotoImage(render_bomb(1.0, 1).resize((64, 64), Image.LANCZOS))
    root.iconphoto(True, icon)
    app.icon = icon
    root.mainloop()


if __name__ == "__main__":
    main()
