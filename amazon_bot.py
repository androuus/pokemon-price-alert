import os, re, json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import requests

URL = "https://www.amazon.es/dp/B0H8T5GC4W"
TARGET_PRICE = 70.00
STATE_FILE = Path("state.json")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def euro(value):
    value = value.replace(".", "").replace(",", ".")
    return float(re.sub(r"[^\d.]", "", value))

def telegram(msg):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": msg, "disable_web_page_preview": False},
        timeout=20,
    )
    r.raise_for_status()

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"alerted": False}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))

def main():
    state = load_state()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-ES",
            timezone_id="Europe/Madrid",
            viewport={"width": 1365, "height": 900},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        )
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # Try to dismiss common consent dialog.
        for selector in [
            "#sp-cc-accept",
            "input[name='accept']",
            "button:has-text('Aceptar')",
            "button:has-text('Aceptar cookies')",
        ]:
            try:
                page.locator(selector).first.click(timeout=1500)
                break
            except Exception:
                pass

        # Product price selectors used by Amazon product pages.
        selectors = [
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            ".a-price .a-offscreen",
        ]
        price = None
        for sel in selectors:
            try:
                txt = page.locator(sel).first.inner_text(timeout=3000).strip()
                if txt:
                    price = euro(txt)
                    break
            except Exception:
                pass

        body = page.locator("body").inner_text(timeout=10000)
        unavailable_phrases = [
            "Actualmente no hay ofertas disponibles",
            "No disponible",
            "Producto no disponible",
        ]
        available = not any(x.lower() in body.lower() for x in unavailable_phrases)

        # A product with an Add to Cart button is a stronger availability signal.
        cart = page.locator("#add-to-cart-button")
        try:
            available = available and cart.count() > 0 and cart.first.is_visible(timeout=1500)
        except Exception:
            pass

        browser.close()

    if price is None:
        raise RuntimeError("No se pudo detectar el precio de Amazon. Puede haber CAPTCHA o un cambio en la página.")

    print(f"Precio: {price:.2f} € | Disponible: {available}")

    qualifies = available and price <= TARGET_PRICE
    if qualifies and not state.get("alerted", False):
        telegram(
            f"🚨 ¡ETB EN OFERTA!\n\n"
            f"💰 Precio: {price:.2f} €\n"
            f"📦 Disponible: Sí\n"
            f"🎯 Límite: {TARGET_PRICE:.2f} €\n\n"
            f"🛒 {URL}"
        )
        state["alerted"] = True
    elif not qualifies:
        state["alerted"] = False

    state["last_price"] = price
    state["last_available"] = available
    save_state(state)

if __name__ == "__main__":
    main()
