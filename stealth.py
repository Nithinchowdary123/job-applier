"""
stealth.py
──────────
Anti-bot-detection utilities:
  - Stealth Playwright browser context (realistic user-agent, viewport, etc.)
  - Human-like typing (character by character with jitter)
  - Human-like mouse movement (bezier curve simulation)
  - Randomised delays with gaussian distribution
  - Session keep-alive (periodic micro-interactions)
"""
from __future__ import annotations
import time, random, math
from datetime import datetime
import pytz
from playwright.sync_api import Page, BrowserContext, Playwright


def is_safe_run_time() -> tuple[bool, str]:
    """
    Returns (True, "") if within safe bot-run window (Mon–Fri 9am–6pm Central).
    Returns (False, reason) if outside safe window.
    """
    from config import BOT_RUN_DAYS, BOT_RUN_START, BOT_RUN_END
    central = pytz.timezone("America/Chicago")
    now = datetime.now(central)
    if now.weekday() not in BOT_RUN_DAYS:
        day_name = now.strftime("%A")
        return False, f"Today is {day_name} — bot only runs Mon–Fri"
    if now.hour < BOT_RUN_START:
        return False, f"Too early ({now.strftime('%I:%M %p')} CT) — starts at 9:00 AM"
    if now.hour >= BOT_RUN_END:
        return False, f"Too late ({now.strftime('%I:%M %p')} CT) — stops at 6:00 PM"
    return True, ""

# ── Realistic browser fingerprint ────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.86 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 800},
]

def make_stealth_context(p: Playwright, headless: bool = False) -> tuple:
    """
    Launch a Chromium browser + stealth context.
    Returns (browser, context, page).
    """
    ua       = random.choice(USER_AGENTS)
    viewport = random.choice(VIEWPORTS)

    browser = p.chromium.launch(
        headless=headless,
        slow_mo=random.randint(30, 70),   # slight global slow-mo
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
            f"--window-size={viewport['width']},{viewport['height']}",
        ]
    )

    context = browser.new_context(
        user_agent=ua,
        viewport=viewport,
        locale="en-US",
        timezone_id="America/Chicago",
        java_script_enabled=True,
        accept_downloads=True,
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }
    )

    # Patch navigator.webdriver = false
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US','en'] });
        window.chrome = { runtime: {} };
    """)

    page = context.new_page()
    return browser, context, page

# ── Human-like delays ─────────────────────────────────────────────────────────

def human_delay(min_s: float = 0.8, max_s: float = 2.5):
    """Gaussian-distributed delay centred between min and max."""
    mu    = (min_s + max_s) / 2
    sigma = (max_s - min_s) / 4
    t     = max(min_s, min(max_s, random.gauss(mu, sigma)))
    time.sleep(t)

def micro_delay():
    """Short pause between keystrokes / micro-interactions."""
    time.sleep(random.uniform(0.05, 0.18))

# ── Human-like typing ─────────────────────────────────────────────────────────

def human_type(page: Page, selector: str, text: str, clear_first: bool = True):
    """
    Type text character-by-character with realistic timing.
    Occasionally pauses mid-word like a real person.
    """
    el = page.query_selector(selector)
    if not el:
        return
    el.click()
    micro_delay()
    if clear_first:
        el.evaluate("el => el.select()")
        micro_delay()

    for i, char in enumerate(text):
        el.type(char, delay=random.randint(40, 130))
        # Occasional longer pause (thinking / typo correction simulation)
        if random.random() < 0.04:
            time.sleep(random.uniform(0.3, 0.8))

def human_fill(page: Page, element, text: str):
    """Fill an already-located element with human-like typing."""
    try:
        element.click(timeout=5000)
    except Exception:
        element.evaluate("el => el.click()")
    micro_delay()
    element.evaluate("el => el.select()")
    micro_delay()
    for char in text:
        element.type(char, delay=random.randint(40, 120))
        if random.random() < 0.03:
            time.sleep(random.uniform(0.2, 0.6))

# ── Human-like mouse movement ─────────────────────────────────────────────────

def _bezier(p0, p1, p2, p3, t):
    """Cubic bezier point at parameter t."""
    return (
        (1-t)**3 * p0[0] + 3*(1-t)**2*t * p1[0] + 3*(1-t)*t**2 * p2[0] + t**3 * p3[0],
        (1-t)**3 * p0[1] + 3*(1-t)**2*t * p1[1] + 3*(1-t)*t**2 * p2[1] + t**3 * p3[1],
    )

def human_move_and_click(page: Page, element):
    """
    Move mouse along a bezier curve to element then click.
    Falls back to direct click if bounding box unavailable.
    """
    try:
        box = element.bounding_box()
        if not box:
            element.click()
            return
        # Target: centre of element with slight random offset
        tx = box["x"] + box["width"]  * random.uniform(0.3, 0.7)
        ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)

        # Current position (approximate — start somewhere on the page)
        sx = random.randint(200, 800)
        sy = random.randint(200, 600)

        # Control points for natural curve
        cp1 = (sx + (tx - sx) * 0.3 + random.randint(-60, 60),
               sy + (ty - sy) * 0.1 + random.randint(-40, 40))
        cp2 = (sx + (tx - sx) * 0.7 + random.randint(-60, 60),
               sy + (ty - sy) * 0.9 + random.randint(-40, 40))

        steps = random.randint(18, 35)
        for i in range(steps + 1):
            t  = i / steps
            pt = _bezier((sx, sy), cp1, cp2, (tx, ty), t)
            page.mouse.move(pt[0], pt[1])
            time.sleep(random.uniform(0.005, 0.018))

        page.mouse.click(tx, ty)
        micro_delay()
    except Exception:
        element.click()

# ── Session keep-alive ────────────────────────────────────────────────────────

def keep_alive_scroll(page: Page):
    """
    Light scroll up/down to signal activity and prevent session timeout.
    Call this every ~90 seconds during long waits.
    """
    try:
        current = page.evaluate("window.scrollY")
        page.evaluate(f"window.scrollTo(0, {current + random.randint(80, 200)})")
        time.sleep(random.uniform(0.4, 0.9))
        page.evaluate(f"window.scrollTo(0, {current})")
    except Exception:
        pass

def periodic_keep_alive(page: Page, last_action_time: float,
                         interval: float = 90.0) -> float:
    """
    Call inside loops. If interval has passed since last_action_time,
    do a keep-alive scroll. Returns updated last_action_time.
    """
    now = time.time()
    if now - last_action_time >= interval:
        keep_alive_scroll(page)
        return now
    return last_action_time
