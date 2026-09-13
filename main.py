import hashlib
import json
import math
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from html import escape
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

FOURCHAMBAULT = (47.0167, 3.0833)
MAX_DISTANCE_KM = float(os.getenv("MAX_DISTANCE_KM", "50"))

SOURCES = [
    ("Brocabrac 58", "https://brocabrac.fr/58/"),
    ("Brocabrac 18", "https://brocabrac.fr/18/"),
    ("Brocabrac 03", "https://brocabrac.fr/03/"),
    ("Vide-Greniers.org Nièvre", "https://vide-greniers.org/evenements/Nievre"),
]

STATE_FILE = "data/state.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; BrocantesAlert/1.0; +https://github.com/)"
}

def haversine(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(h))

def geocode(place):
    """Best-effort geocoding with Nominatim. Respectful rate limit."""
    if not place:
        return None
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{place}, France", "format": "json", "limit": 1},
            headers={**HEADERS, "Referer": "https://github.com/"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"[geocode] {place}: {e}")
    return None

def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()

def parse_date(text):
    text = clean(text)
    # Common French date formats.
    months = {
        "janvier":1, "février":2, "mars":3, "avril":4, "mai":5, "juin":6,
        "juillet":7, "août":8, "septembre":9, "octobre":10, "novembre":11, "décembre":12
    }
    m = re.search(r"(\d{1,2})\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})", text.lower())
    if m:
        return f"{m.group(3)}-{months[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""

def extract_events(source_name, url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    events = []

    # Generic extraction intentionally conservative: event-like links only.
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        href = urljoin(url, a["href"])
        if len(title) < 8 or len(title) > 180:
            continue
        if not any(k in title.lower() for k in ("brocante", "vide-grenier", "vide grenier", "foire", "puces", "braderie")):
            continue

        container = a.find_parent(["article", "li", "div"])
        block = clean(container.get_text(" ", strip=True)) if container else title
        date = parse_date(block)
        if not date:
            continue

        # Try to infer a French locality from common text around the link.
        ville = ""
        m = re.search(r"\b(?:à|a|-)\s+([A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ][A-Za-zÀ-ÿ'’ -]{2,50})", block)
        if m:
            ville = clean(m.group(1)).strip(" -,:;.")
        if not ville:
            ville = clean(source_name.replace("Brocabrac ", "").replace(" Nièvre", ""))

        events.append({
            "title": title,
            "date": date,
            "ville": ville,
            "address": "",
            "url": href,
            "source": source_name,
        })

    # Deduplicate parser results.
    unique = {}
    for e in events:
        key = (e["title"].lower(), e["date"], e["ville"].lower())
        unique[key] = e
    return list(unique.values())

def event_id(e):
    raw = f'{clean(e["title"]).lower()}|{e["date"]}|{clean(e["ville"]).lower()}'
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)

def enrich(events):
    out = []
    cache = {}
    for e in events:
        place = e["ville"] or e["address"]
        if place not in cache:
            cache[place] = geocode(place)
        coords = cache[place]
        if not coords:
            print(f"[skip] coordonnées introuvables: {place}")
            continue
        e["distance_km"] = round(haversine(FOURCHAMBAULT, coords), 1)
        e["lat"], e["lon"] = coords
        if e["distance_km"] <= MAX_DISTANCE_KM:
            out.append(e)
    return out

def maps_links(e):
    destination = quote(f'{e["address"] or e["ville"]}, France')
    return (
        f"https://www.google.com/maps/dir/?api=1&destination={destination}",
        f"https://maps.apple.com/?daddr={destination}",
    )

def make_html(e, detected):
    gmaps, apple = maps_links(e)
    return f"""<!doctype html>
<html lang="fr"><body style="font-family:Arial,sans-serif;background:#f4f6f8;padding:24px">
<div style="max-width:620px;margin:auto;background:white;border-radius:14px;padding:28px">
<h1 style="margin-top:0">📢 Nouvelle brocante</h1>
<h2>{escape(e['title'])}</h2>
<p>📅 <b>Date :</b> {escape(e['date'])}</p>
<p>🏘️ <b>Ville :</b> {escape(e['ville'])}</p>
<p>📍 <b>Adresse :</b> {escape(e['address'] or 'Non précisée')}</p>
<p>📏 <b>Distance :</b> {e['distance_km']} km depuis Fourchambault</p>
<p>
<a href="{escape(e['url'])}" style="display:inline-block;padding:10px 14px;background:#222;color:white;text-decoration:none;border-radius:8px">Ouvrir la fiche</a>
</p>
<p>
<a href="{gmaps}">🚗 Google Maps</a> &nbsp; · &nbsp;
<a href="{apple}">🍎 Apple Plans</a>
</p>
<hr>
<p>🌐 Source : <a href="{escape(e['url'])}">{escape(e['source'])}</a></p>
<p style="color:#666;font-size:12px">Détection : {escape(detected)}</p>
<hr>
<p><a href="mailto:brocanteinfoo@gmail.com?subject=DESABONNEMENT%20-%20Alertes%20brocantes&body=Bonjour%2C%0A%0AMerci%20de%20désabonner%20cette%20adresse%20des%20alertes%20brocantes.">🔕 Se désabonner des alertes</a></p>
</div></body></html>"""

def send_email(events):
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipients = [x.strip() for x in os.environ.get("EMAIL_TO", "").split(",") if x.strip()]
    cc = [x.strip() for x in os.environ.get("EMAIL_CC", "").split(",") if x.strip()]
    bcc = [x.strip() for x in os.environ.get("EMAIL_BCC", "").split(",") if x.strip()]
    if not recipients:
        raise RuntimeError("EMAIL_TO est vide.")

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "465"))
    detected = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y à %H:%M")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
        server.login(user, password)
        for e in events:
            msg = EmailMessage()
            msg["From"] = user
            msg["To"] = ", ".join(recipients)
            if cc:
                msg["Cc"] = ", ".join(cc)
            msg["Subject"] = f"📢 Nouvelle brocante à {e['distance_km']} km — {e['ville']}"
            msg.set_content(
                f"{e['title']}\nDate: {e['date']}\nVille: {e['ville']}\n"
                f"Distance: {e['distance_km']} km\nSource: {e['url']}"
            )
            msg.add_alternative(make_html(e, detected), subtype="html")
            server.send_message(msg, to_addrs=recipients + cc + bcc)

def main():
    state = load_state()
    all_events = []
    for source, url in SOURCES:
        try:
            print(f"[fetch] {source}: {url}")
            all_events.extend(extract_events(source, url))
        except Exception as e:
            print(f"[error] {source}: {e}")

    candidates = enrich(all_events)
    new_events = []
    for e in candidates:
        eid = event_id(e)
        if eid not in state["seen"]:
            state["seen"][eid] = {
                "title": e["title"], "date": e["date"], "ville": e["ville"],
                "first_seen": datetime.now(timezone.utc).isoformat()
            }
            new_events.append(e)

    if new_events:
        print(f"[new] {len(new_events)} événement(s)")
        send_email(new_events)
    else:
        print("[new] Aucun nouvel événement.")

    # Keep state bounded.
    if len(state["seen"]) > 10000:
        state["seen"] = dict(list(state["seen"].items())[-8000:])
    save_state(state)

if __name__ == "__main__":
    main()
