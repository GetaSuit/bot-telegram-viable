import os
import json
import re
import time
import random
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, SCRAPFLY_KEY

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────

def parse_price(raw) -> float | None:
    try:
        if isinstance(raw, dict):
            if raw.get("cents"):
                return float(raw["cents"]) / 100
            v = raw.get("amount") or raw.get("value", "")
        else:
            v = raw
        return float(str(v).replace(",", ".").replace("€", "").replace(" ", ""))
    except Exception:
        return None

def price_ok(raw) -> bool:
    p = parse_price(raw)
    return p is not None and MIN_PRICE <= p <= MAX_PRICE

def title_ok(title: str, brand: str) -> bool:
    if not title or not brand:
        return False
    tl = title.lower()
    if brand.lower() not in tl:
        return False
    for kw in HARD_EXCLUDES:
        if kw in tl:
            return False
    return True

def scrapfly(url: str) -> str | None:
    if not SCRAPFLY_KEY:
        return None
    try:
        r = requests.get(
            "https://api.scrapfly.io/scrape",
            params={
                "key": SCRAPFLY_KEY,
                "url": url,
                "asp": "true",
                "render_js": "true",
                "country": "fr",
            },
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"[ScrapFly] {r.status_code} — {url[:60]}")
            return None
        return r.json().get("result", {}).get("content", "")
    except Exception as e:
        logger.error(f"[ScrapFly] {e}")
        return None

def next_data(html: str) -> dict:
    if not html:
        return {}
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


# ──────────────────────────────────────────
# VINTED — nouvelles annonces
# ──────────────────────────────────────────

def fetch_vinted_new(brand: str) -> list:
    """Récupère les annonces les plus récentes pour une marque."""
    url = (
        f"https://www.vinted.fr/catalog"
        f"?search_text={brand.replace(' ', '+')}"
        f"&price_from={MIN_PRICE}&price_to={MAX_PRICE}"
        f"&currency=EUR&page=1&order=newest_first"
    )

    html = scrapfly(url)
    nd = next_data(html)
    if not nd:
        logger.warning(f"[Vinted] Pas de données pour '{brand}'")
        return []

    page_props = nd.get("props", {}).get("pageProps", {})
    items = []

    # Cherche dans plusieurs structures
    ci = page_props.get("catalogItems", {})
    if ci:
        items = ci.get("catalogItems", ci.get("items", []))
    if not items:
        items = page_props.get("items", [])
    if not items:
        state = page_props.get("initialState", {})
        items = state.get("catalog", {}).get("items", [])
    if not items:
        # Cherche dans tout le JSON
        raw = json.dumps(nd)
        for pattern in [r'"catalogItems":\s*(\[.*?\])', r'"items":\s*(\[.*?\])']:
            for m in re.findall(pattern, raw, re.DOTALL):
                try:
                    candidate = json.loads(m)
                    if candidate and len(candidate) > 1:
                        items = candidate
                        break
                except Exception:
                    continue
            if items:
                break

    results = []
    for item in items:
        title = item.get("title", "")
        price_raw = item.get("price")
        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        photo = item.get("photo") or {}
        image = photo.get("url") or photo.get("full_size_url")
        item_id = item.get("id", "")
        size = item.get("size", {})
        size_str = ""
        if isinstance(size, dict):
            size_str = size.get("title", "")
        elif isinstance(size, str):
            size_str = size

        results.append({
            "id": str(item_id),
            "title": title,
            "price": price,
            "size": size_str,
            "url": f"https://www.vinted.fr/items/{item_id}",
            "image": image,
            "source": "Vinted",
            "brand": brand,
        })

    logger.info(f"[Vinted] {len(results)} nouvelles annonces pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE — nouvelles annonces
# ──────────────────────────────────────────

def fetch_vestiaire_new(brand: str) -> list:
    """Récupère les annonces les plus récentes pour une marque."""
    url = (
        f"https://www.vestiairecollective.com/search/"
        f"?q={brand.replace(' ', '+')}"
        f"&priceMin={MIN_PRICE}&priceMax={MAX_PRICE}"
        f"&sort=1&page=1"  # sort=1 = plus récent
    )

    html = scrapfly(url)
    nd = next_data(html)
    if not nd:
        logger.warning(f"[VC] Pas de données pour '{brand}'")
        return []

    page_props = nd.get("props", {}).get("pageProps", {})
    items = []

    # Structure 1 — dehydratedState
    dehydrated = page_props.get("dehydratedState", {})
    if dehydrated:
        for query in dehydrated.get("queries", []):
            data = query.get("state", {}).get("data", {})
            if isinstance(data, dict):
                for key in ["items", "products", "results", "catalogItems"]:
                    candidate = data.get(key, [])
                    if candidate and isinstance(candidate, list) and len(candidate) > 1:
                        items = candidate
                        break
            if items:
                break

    # Structure 2 — pageProps directs
    if not items:
        for key in ["items", "products", "catalogItems"]:
            items = page_props.get(key, [])
            if items:
                break

    # Structure 3 — cherche dans tout le JSON
    if not items:
        raw = json.dumps(nd)
        for pattern in [r'"items":\s*(\[.*?\])', r'"products":\s*(\[.*?\])']:
            for m in re.findall(pattern, raw, re.DOTALL):
                try:
                    candidate = json.loads(m)
                    if candidate and len(candidate) > 2:
                        items = candidate
                        break
                except Exception:
                    continue
            if items:
                break

    results = []
    for item in items:
        title = item.get("name", "") or item.get("title", "")
        price_obj = item.get("price", {})

        if isinstance(price_obj, dict):
            cents = price_obj.get("cents")
            price_raw = cents / 100 if cents else price_obj.get("amount") or price_obj.get("value")
        else:
            price_raw = price_obj

        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        link = item.get("link", item.get("url", ""))
        if link and not link.startswith("http"):
            link = "https://www.vestiairecollective.com" + link

        image = None
        if item.get("pictures"):
            image = item["pictures"][0].get("url")
        elif item.get("picture"):
            image = item["picture"].get("url")

        size_str = ""
        size = item.get("size", {})
        if isinstance(size, dict):
            size_str = size.get("name", "") or size.get("title", "")
        elif isinstance(size, str):
            size_str = size

        item_id = str(item.get("id", link))

        results.append({
            "id": item_id,
            "title": title,
            "price": price,
            "size": size_str,
            "url": link,
            "image": image,
            "source": "Vestiaire Collective",
            "brand": brand,
        })

    logger.info(f"[VC] {len(results)} nouvelles annonces pour '{brand}'")
    return results


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def fetch_new(brand: str) -> list:
    results = []
    results.extend(fetch_vinted_new(brand))
    time.sleep(random.uniform(1, 2))
    results.extend(fetch_vestiaire_new(brand))
    return results
