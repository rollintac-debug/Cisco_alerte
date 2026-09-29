import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = os.environ["PAGE_URL"]
TOPIC = os.environ["NTFY_TOPIC"]
TARGET = os.environ.get("TARGET_OFFER", "").strip() or "Basic Plus"
TEST_MODE = os.environ.get("TEST_MODE", "").strip() in ("1", "true", "oui")
STATE = Path("state.json")
OFFERS = ["Basic", "Basic Plus", "VIP", "VIP Premium"]

JS = """
(offers) => {
  const out = {};
  const els = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,p,span,div'));
  for (const name of offers) {
    const title = els.find(e => e.children.length === 0 &&
                    e.textContent.trim().toLowerCase() === name.toLowerCase());
    if (!title) { out[name] = null; continue; }
    let card = title, btns = [];
    for (let i = 0; i < 8 && card.parentElement; i++) {
      card = card.parentElement;
      btns = Array.from(card.querySelectorAll('button, a'))
               .filter(b => b.textContent.trim().length > 0);
      if (btns.length) break;
    }
    out[name] = btns.slice(0, 3).map(b => ({
      label: b.textContent.trim().replace(/\\s+/g, ' ').slice(0, 60),
      disabled: !!(b.disabled || b.getAttribute('aria-disabled') === 'true' ||
                   /disabled|inactive|soldout|sold-out/i.test(b.className)),
      href: (b.getAttribute('href') || '').slice(0, 200),
    }));
  }
  return out;
}
"""


def notify(title, message, priority="urgent"):
    level = {"urgent": 5, "high": 4, "default": 3}.get(priority, 3)
    requests.post("https://ntfy.sh/", json={
        "topic": TOPIC, "title": title, "message": message, "priority": level,
        "tags": ["soccer", "rotating_light"], "click": URL}, timeout=15)
    print(f"NOTIF [{priority}] {title} - {message}")


def describe(buttons):
    if buttons is None:
        return "offre absente de la page"
    if not buttons:
        return "aucun bouton"
    return " | ".join(f"{b['label']}{' (GRISÉ)' if b['disabled'] else ' (actif)'}"
                      for b in buttons)


def read_page():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(locale="fr-FR", user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"))
        resp = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        code = resp.status if resp else 0
        offers = page.evaluate(JS, OFFERS)
        browser.close()
    return code, offers


state = json.loads(STATE.read_text()) if STATE.exists() else {}
first_run = state.get("url") != URL or state.get("target") != TARGET
now = datetime.now(timezone.utc).isoformat(timespec="seconds")

try:
    code, offers = read_page()
except Exception as e:
    code, offers = 0, {}
    print(f"Erreur navigateur : {e}")

print(f"{now}  HTTP {code}")
for name in OFFERS:
    print(f"  {name:<12} {describe(offers.get(name))}")

target_key = next((n for n in OFFERS if n.lower() == TARGET.lower()), TARGET)
current = describe(offers.get(target_key))

if code != 200 or not offers:
    if first_run or state.get("last_code") == 200:
        notify("Surveillance Clásico : page illisible",
               f"HTTP {code}. La surveillance ne voit pas la page.", "default")
elif TEST_MODE:
    buttons = offers.get(target_key) or []
    if any(not b["disabled"] for b in buttons):
        notify(f"TEST OK : {target_key} en vente !",
               f"{current}\nLa détection et les notifications fonctionnent.")
    else:
        notify(f"TEST : {target_key} pas détectée en vente",
               "\n".join(f"{n} : {describe(offers.get(n))}" for n in OFFERS),
               "default")
elif first_run:
    resume = "\n".join(f"{n} : {describe(offers.get(n))}" for n in OFFERS)
    notify(f"Surveillance lancée ({target_key})", resume, "default")
elif current != state.get("target_status"):
    notify(f"Clásico : {target_key} a changé !",
           f"Avant : {state.get('target_status')}\nMaintenant : {current}")

state.update({"url": URL, "target": TARGET, "last_code": code,
              "target_status": current, "last_check": now,
              "all": {n: describe(offers.get(n)) for n in OFFERS}})
STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
