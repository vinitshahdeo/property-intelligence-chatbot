import re
import requests
from .config import (OPENROUTER_API_KEY, OPENROUTER_MODEL,
                     OPENROUTER_SITE_URL, OPENROUTER_APP_NAME)

def answer_with_openrouter(question, history, docs):
    if not OPENROUTER_API_KEY:
        return None
    context = "\n\n".join(
        f"[{i+1}] Source: {d['source']} | Title: {d['title']} | URL: {d['url']}\n{d['content'][:2600]}"
        for i, d in enumerate(docs)
    )
    messages = [{
        "role": "system",
        "content": (
            "You are a careful property research assistant for DarGlobal and Wasalt. "
            "Answer ONLY from the supplied source excerpts. Do not invent prices, availability, "
            "amenities, project details, or legal/financial advice. If evidence is insufficient, "
            "say so and suggest what data is needed. Distinguish the two sources. "
            "Cite factual claims inline as [1], [2], matching the supplied excerpts. "
            "Never imply listings are current unless the source explicitly establishes that."
            "\n\nSOURCE EXCERPTS:\n" + (context or "No matching source excerpts were retrieved.")
        )
    }]
    for item in (history or [])[-6:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])[:2000]})
    messages.append({"role": "user", "content": question})
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-Title": OPENROUTER_APP_NAME
        },
        json={"model": OPENROUTER_MODEL, "messages": messages, "temperature": 0.2},
        timeout=45
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]

def _price(p):
    """'65000 SAR /Year' -> (65000.0, 'SAR', '/yr')"""
    m = re.match(r"\s*([\d.,]+)\s*([A-Z]{3})?\s*(/\s*\w+)?", p or "")
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(3) or "").replace(" ", "").lower()
    unit = {"/year": "/yr", "/month": "/mo", "/day": "/night"}.get(unit, unit)
    return value, m.group(2) or "SAR", unit

def _fmt_price(v, cur, unit):
    return f"{cur} {v:,.0f}{unit}"

def grounded_fallback(question, docs):
    if not docs:
        return ("I couldn't find anything matching that in the indexed listings. "
                "Try a city (Riyadh, Jeddah, Khobar), a property type, or rent vs. sale.")
    listings = [d for d in docs if "/property/" in d["url"] or "/dailyrental/" in d["url"]]
    parts = [f"I found {len(docs)} matching {'page' if len(docs) == 1 else 'pages'}"
             + (f", including {len(listings)} individual {'listing' if len(listings) == 1 else 'listings'}" if listings else "")
             + "."]
    priced = [(i, _price(d.get("price"))) for i, d in enumerate(docs, 1)]
    priced = [(i, p) for i, p in priced if p]
    if priced:
        groups = {}
        for i, (v, cur, unit) in priced:
            groups.setdefault((cur, unit), []).append((v, i))
        (cur, unit), items = max(groups.items(), key=lambda kv: len(kv[1]))
        (lo, lo_i), (hi, hi_i) = min(items), max(items)
        if lo == hi:
            parts.append(f"The listed price is **{_fmt_price(lo, cur, unit)}** [{lo_i}].")
        else:
            parts.append(f"Listed prices range from **{_fmt_price(lo, cur, '')}** [{lo_i}] "
                         f"to **{_fmt_price(hi, cur, unit)}** [{hi_i}].")
    areas = []
    for d in docs:
        loc = (d.get("location") or "").split(",")[0].strip()
        if loc and loc != "Saudi Arabia" and loc not in areas:
            areas.append(loc)
    if areas:
        parts.append("Areas include " + ", ".join(areas[:4]) + ".")
    parts.append("Open a source below for full details.")
    return " ".join(parts)
