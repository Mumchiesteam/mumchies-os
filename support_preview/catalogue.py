"""Read-only public Shopify catalogue snapshot, cached and bounded."""
import asyncio
import html
import re
import time
from urllib.parse import urlparse
import httpx

SHOP = "https://mumchies.com"
CACHE_TTL = 900
_cache = {"until": 0.0, "items": [], "error": None}
_lock = asyncio.Lock()

def clean(value, limit=280):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\\s+", " ", html.unescape(value)).strip()[:limit]

async def catalogue():
    now = time.monotonic()
    if now < _cache["until"]:
        return _cache["items"], _cache["error"]
    async with _lock:
        if time.monotonic() < _cache["until"]:
            return _cache["items"], _cache["error"]
        products = []
        error = None
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
                for page in range(1, 6):
                    response = await client.get(SHOP + "/products.json", params={"limit": 250, "page": page},
                        headers={"Accept": "application/json"})
                    response.raise_for_status()
                    batch = response.json().get("products")
                    if not isinstance(batch, list):
                        raise ValueError("invalid catalogue")
                    for p in batch:
                        handle = str(p.get("handle") or "")
                        if not re.fullmatch(r"[a-z0-9-]{1,150}", handle):
                            continue
                        variants = p.get("variants") or []
                        products.append({
                            "name": clean(p.get("title"), 110),
                            "type": clean(p.get("product_type"), 65),
                            "description": clean(p.get("body_html"), 340),
                            "tags": clean(p.get("tags"), 150),
                            "url": SHOP + "/products/" + handle,
                            "prices_inr": sorted(set(str(v.get("price")) for v in variants if v.get("price")))[:6],
                            "variants": [clean(v.get("title"), 70) for v in variants[:8]],
                            "listed_online": True,
                        })
                    if len(batch) < 250:
                        break
            if not products:
                raise ValueError("empty catalogue")
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            error = "Public Shopify catalogue temporarily unavailable"
        if products:
            _cache.update(items=products[:1250], error=None, until=time.monotonic() + CACHE_TTL)
        else:
            # Preserve last good snapshot; don't treat it as live stock.
            _cache.update(error=error, until=time.monotonic() + 120)
        return _cache["items"], _cache["error"]

def select_products(items, message, history, max_items=45):
    # Broad questions get representative names; specific questions get matching entries.
    # Explicit new category overrides earlier topics (e.g. noodles, not pasta).\n    context = message.casefold()\n    if len(context.split()) <= 2 and context.strip() in {"yes", "ji", "haan", "link", "links", "ok"}:\n        context = " ".join([str(t.content) for t in history[-3:]] + [message]).casefold()
    terms = set(re.findall(r"[a-z]{3,}", context))
    aliases = {"namkeen": {"savoury", "savory", "mixture", "chivda", "snack"},
               "mithai": {"sweet", "laddu", "katli"}, "ladoo": {"laddu"},
               "makhana": {"foxnut"}, "spicy": {"masala", "chilli", "chili"}}
    expanded = set(terms)
    for word, extras in aliases.items():
        if word in terms:
            expanded.update(extras)
    # Keep pasta and noodles distinct even if their descriptions mention each other.\n    wants_noodles = bool(re.search(r"\\b(noodles?|noodle|nudles?)\\b", context))\n    wants_pasta = bool(re.search(r"\\bpasta\\b", context)) and not wants_noodles\n    if wants_noodles:\n        items = [p for p in items if re.search(r"\\bnoodles?\\b", p["name"], re.I)]\n    elif wants_pasta:\n        items = [p for p in items if "pasta" in p["name"].casefold()]\n    scored = []
    for p in items:
        name = p["name"].casefold()
        description = (p["type"] + " " + p["tags"]).casefold()
        score = sum(5 for t in expanded if t in name) + sum(1 for t in expanded if t in description)
        if score:
            scored.append((score, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return items[:max_items]
    return [p for _, p in scored[:max_items]]
