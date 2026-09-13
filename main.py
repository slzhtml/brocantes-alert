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
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; BrocantesAlert/1.0; +https://github.com/)"
    )
}


def haversine(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def geocode(place):
    """Best-effort geocoding with Nominatim."""

    if not place:
        return None

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{place}, France",
                "format": "json",
                "limit": 1,
            },
            headers={
                **HEADERS,
                "Referer": "https://github.com/",
            },
            timeout=15,
        )

        r.raise_for_status()

        data = r.json()

        if data:
            return (
                float(data[0]["lat"]),
                float(data[0]["lon"]),
            )

    except Exception as e:
        print(f"[geocode] {place}: {e}")

    return None


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def parse_date(text):
    text = clean(text)

    months = {
        "janvier": 1,
        "février": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "août": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "décembre": 12,
    }

    m = re.search(
        r"(\d{1,2})\s+"
        r"(janvier|février|mars|avril|mai|juin|juillet|août|septembre|"
        r"octobre|novembre|décembre)\s+"
        r"(\d{4})",
        text.lower(),
    )

    if m:
        return (
            f"{m.group(3)}-"
            f"{months[m.group(2)]:02d}-"
            f"{int(m.group(1)):02d}"
        )

    m = re.search(
        r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b",
        text,
    )

    if m:
        return (
            f"{m.group(3)}-"
            f"{int(m.group(2)):02d}-"
            f"{int(m.group(1)):02d}"
        )

    return ""


def extract_events(source_name, url):
    r = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    r.raise_for_status()

    soup = BeautifulSoup(
        r.text,
        "html.parser",
    )

    events = []

    for a in soup.find_all("a", href=True):
        title = clean(
            a.get_text(" ", strip=True)
        )

        href = urljoin(
            url,
            a["href"],
        )

        if len(title) < 8 or len(title) > 180:
            continue

        if not any(
            k in title.lower()
            for k in (
                "brocante",
                "vide-grenier",
                "vide grenier",
                "foire",
                "puces",
                "braderie",
            )
        ):
            continue

        container = a.find_parent(
            ["article", "li", "div"]
        )

        block = (
            clean(
                container.get_text(
                    " ",
                    strip=True,
                )
            )
            if container
            else title
        )

        date = parse_date(block)

        if not date:
            continue

        ville = ""

        m = re.search(
            r"\b(?:à|a|-)\s+"
            r"([A-ZÀÂÄÇÉÈÊËÎÏÔÖÙÛÜŸ]"
            r"[A-Za-zÀ-ÿ'’ -]{2,50})",
            block,
        )

        if m:
            ville = clean(
                m.group(1)
            ).strip(" -,:;.")

        if not ville:
            ville = clean(
                source_name
                .replace("Brocabrac ", "")
                .replace(" Nièvre", "")
            )

        events.append(
            {
                "title": title,
                "date": date,
                "ville": ville,
                "address": "",
                "url": href,
                "source": source_name,
            }
        )

    unique = {}

    for e in events:
        key = (
            e["title"].lower(),
            e["date"],
            e["ville"].lower(),
        )

        unique[key] = e

    return list(unique.values())


def event_id(e):
    raw = (
        f'{clean(e["title"]).lower()}|'
        f'{e["date"]}|'
        f'{clean(e["ville"]).lower()}'
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def load_state():
    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except FileNotFoundError:
        return {"seen": {}}


def save_state(state):
    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True,
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def enrich(events):
    out = []
    cache = {}

    for e in events:
        place = e["ville"] or e["address"]

        if place not in cache:
            cache[place] = geocode(place)

        coords = cache[place]

        if not coords:
            print(
                f"[skip] coordonnées introuvables: {place}"
            )
            continue

        e["distance_km"] = round(
            haversine(
                FOURCHAMBAULT,
                coords,
            ),
            1,
        )

        e["lat"], e["lon"] = coords

        if e["distance_km"] <= MAX_DISTANCE_KM:
            out.append(e)

    return out


def maps_links(e):
    destination = quote(
        f'{e["address"] or e["ville"]}, France'
    )

    return (
        "https://www.google.com/maps/dir/"
        f"?api=1&destination={destination}",
        f"https://maps.apple.com/?daddr={destination}",
    )


def make_html(e, detected, test=False):
    gmaps, apple = maps_links(e)

    title = (
        "🧪 TEST — Brocante"
        if test
        else "📢 Nouvelle brocante"
    )

    return f"""<!doctype html>
<html lang="fr">

<body style="
font-family:Arial,sans-serif;
background:#f4f6f8;
padding:24px
">

<div style="
max-width:620px;
margin:auto;
background:white;
border-radius:14px;
padding:28px
">

<h1 style="margin-top:0">
{title}
</h1>

<h2>{escape(e['title'])}</h2>

<p>
📅 <b>Date :</b>
{escape(e['date'])}
</p>

<p>
🏘️ <b>Ville :</b>
{escape(e['ville'])}
</p>

<p>
📍 <b>Adresse :</b>
{escape(e['address'] or 'Non précisée')}
</p>

<p>
📏 <b>Distance :</b>
{e['distance_km']} km depuis Fourchambault
</p>

<p>
<a
href="{escape(e['url'])}"
style="
display:inline-block;
padding:10px 14px;
background:#222;
color:white;
text-decoration:none;
border-radius:8px
">
Ouvrir la fiche
</a>
</p>

<p>
<a href="{gmaps}">
🚗 Google Maps
</a>
&nbsp; · &nbsp;
<a href="{apple}">
🍎 Apple Plans
</a>
</p>

<hr>

<p>
🌐 Source :
<a href="{escape(e['url'])}">
{escape(e['source'])}
</a>
</p>

<p style="color:#666;font-size:12px">
Détection :
{escape(detected)}
</p>

<hr>

<p>
<a href="mailto:brocanteinfoo@gmail.com?subject=DESABONNEMENT%20-%20Alertes%20brocantes&body=Bonjour%2C%0A%0AMerci%20de%20désabonner%20cette%20adresse%20des%20alertes%20brocantes.">
🔕 Se désabonner des alertes
</a>
</p>

</div>

</body>
</html>"""


def send_email(events, test=False):
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    recipients = [
        x.strip()
        for x in os.environ.get(
            "EMAIL_TO",
            "",
        ).split(",")
        if x.strip()
    ]

    cc = [
        x.strip()
        for x in os.environ.get(
            "EMAIL_CC",
            "",
        ).split(",")
        if x.strip()
    ]

    bcc = [
        x.strip()
        for x in os.environ.get(
            "EMAIL_BCC",
            "",
        ).split(",")
        if x.strip()
    ]

    if not recipients:
        raise RuntimeError(
            "EMAIL_TO est vide."
        )

    smtp_host = os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "465",
        )
    )

    detected = (
        datetime.now(timezone.utc)
        .astimezone()
        .strftime(
            "%d/%m/%Y à %H:%M"
        )
    )

    context = ssl.create_default_context()

    with smtplib.SMTP_SSL(
        smtp_host,
        smtp_port,
        context=context,
    ) as server:

        print(
            "[email] Connexion à Gmail..."
        )

        server.login(
            user,
            password,
        )

        print(
            "[email] Authentification Gmail OK."
        )

        for e in events:
            msg = EmailMessage()

            msg["From"] = user
            msg["To"] = ", ".join(
                recipients
            )

            if cc:
                msg["Cc"] = ", ".join(cc)

            if test:
                msg["Subject"] = (
                    f"🧪 TEST — {e['title']} "
                    f"({e['ville']})"
                )
            else:
                msg["Subject"] = (
                    f"📢 Nouvelle brocante à "
                    f"{e['distance_km']} km — "
                    f"{e['ville']}"
                )

            msg.set_content(
                f"{e['title']}\n"
                f"Date: {e['date']}\n"
                f"Ville: {e['ville']}\n"
                f"Distance: "
                f"{e['distance_km']} km\n"
                f"Source: {e['url']}"
            )

            msg.add_alternative(
                make_html(
                    e,
                    detected,
                    test=test,
                ),
                subtype="html",
            )

            server.send_message(
                msg,
                to_addrs=(
                    recipients
                    + cc
                    + bcc
                ),
            )

            print(
                f"[email] Envoyé : "
                f"{e['title']} "
                f"({e['ville']})"
            )


def test_email(events):
    """
    Mode test :
    envoie les brocantes actuellement
    présentes sur les sites, même si elles
    sont déjà enregistrées dans state.json.

    IMPORTANT :
    ce mode ne modifie pas state.json.
    """

    print("")
    print("====================================")
    print("       MODE TEST DES E-MAILS")
    print("====================================")
    print("")

    if not events:
        print(
            "[email-test] "
            "Aucune brocante trouvée dans "
            "le rayon configuré."
        )
        return

    print(
        f"[email-test] "
        f"{len(events)} brocante(s) "
        f"à envoyer."
    )

    print(
        f"[email-test] "
        f"Rayon maximum : "
        f"{MAX_DISTANCE_KM} km"
    )

    print("")

    send_email(
        events,
        test=True,
    )

    print("")
    print(
        "[email-test] "
        "✅ Test terminé."
    )


def fetch_and_enrich():
    """
    Récupère les événements des sites
    puis les géocode.
    """

    all_events = []

    for source, url in SOURCES:
        try:
            print(
                f"[fetch] {source}: {url}"
            )

            events = extract_events(
                source,
                url,
            )

            print(
                f"[fetch] {source}: "
                f"{len(events)} événement(s) trouvé(s)"
            )

            all_events.extend(events)

        except Exception as e:
            print(
                f"[error] {source}: {e}"
            )

    print("")
    print(
        f"[fetch] Total brut : "
        f"{len(all_events)} événement(s)"
    )

    candidates = enrich(
        all_events
    )

    print(
        f"[geo] Total dans le rayon : "
        f"{len(candidates)} événement(s)"
    )

    return candidates


def main():
    state = load_state()

    candidates = fetch_and_enrich()

    new_events = []

    for e in candidates:
        eid = event_id(e)

        if eid not in state["seen"]:

            state["seen"][eid] = {
                "title": e["title"],
                "date": e["date"],
                "ville": e["ville"],
                "first_seen": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
            }

            new_events.append(e)

    if new_events:
        print(
            f"[new] "
            f"{len(new_events)} événement(s)"
        )

        send_email(
            new_events,
            test=False,
        )

    else:
        print(
            "[new] Aucun nouvel événement."
        )

    if len(state["seen"]) > 10000:
        state["seen"] = dict(
            list(
                state["seen"].items()
            )[-8000:]
        )

    save_state(state)


if __name__ == "__main__":

    # ==================================================
    # TEST_EMAIL=true
    #
    # Envoie les brocantes déjà présentes sur les sites
    # même si elles existent déjà dans state.json.
    #
    # Le fichier state.json n'est PAS modifié.
    # ==================================================

    if (
        os.getenv(
            "TEST_EMAIL",
            "",
        ).lower()
        == "true"
    ):
        candidates = fetch_and_enrich()
        test_email(candidates)

    else:
        main()
