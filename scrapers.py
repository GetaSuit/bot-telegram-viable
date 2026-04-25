import os
import json
import re
import time
import random
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, SCRAPFLY_KEY

logger = logging.getLogger(__name__)

MAX_PER_SOURCE = 20


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


# ──────────────────────────────────────────
# SCRAPFLY — session en 2 étapes
# ──────────────────────────────────────────

def scrapfly_session_then_api(session_url: str, api_url: str, api_headers: dict) -> dict | None:
    """
    Étape 1 : visite la page principale pour obtenir les cookies.
    Étape 2 : appelle l'API avec ces cookies.
    """
    if not SCRAPFLY_KEY:
        logger.error("[ScrapFly] Clé manquante")
        return None

    try:
        # Étape 1 — initialise la session
        r1 = requests.get(
            "https://api.scrapfly.io/scrape",
            params={
                "key": SCRAPFLY_KEY,
                "url": session_url,
                "asp": "true",
                "render_js": "true",
                "country": "fr",
                "session": "vinted_session",
            },
            timeout=30,
        )
        if r1.status_code != 200:
            logger.warning(f"[ScrapFly] Session init: {r1.status_code}")
            return None

        time.sleep(2)

        # Étape 2 — appelle l'API avec la session
        r2 = requests.get(
            "https://api.scrapfly.io/scrape",
            params={
                "key": SCRAPFLY_KEY,
                "url": api_url,
                "asp": "true",
                "country": "fr",
                "session": "vinted_session",
                "headers": json.dumps(api_headers),
            },
            timeout=30,
        )
        if r2.status_code != 200:
            logger.warning(f"[ScrapFly] API: {r2.status_code}")
            return None

        content = r2.json().get("result", {}).get("content", "")
        if not content:
            return None

        return json.loads(content)

    except Exception as e:
        logger.error(f"[ScrapFly] {e}")
        return None


def scrapfly_simple(url: str, headers: dict = None, render_js: bool = False) -> str | None:
    """Appel ScrapFly simple."""
    if not SCRAPFLY_KEY:
        return None
    try:
        params = {
            "key": SCRAPFLY_KEY,
            "url": url,
            "asp": "true",
            "country": "fr",
        }
        if render_js:
            params["render_js"] = "true"
        if headers:
            params["headers"] = json.dumps(headers)

        r = requests.get(
            "https://api.scrapfly.io/scrape",
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"[ScrapFly] {r.status_code} — {url[:60]}")
            return None

        return r.json().get("result", {}).get("content", "")
    except Exception as e:
        logger.error(f"[ScrapFly] {e}")
        return None


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

def fetch_vinted_new(brand: str) -> list:
    logger.info(f"[Vinted] Recherche '{brand}'...")

    api_url = (
        f"https://www.vinted.fr/api/v2/catalog/items"
        f"?search_text={brand.replace(' ', '%20')}"
        f"&price_from={MIN_PRICE}&price_to={MAX_PRICE}"
        f"&currency=EUR&per_page=50&page=1&order=newest_first"
    )

    api_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Origin": "https://www.vinted.fr",
        "Referer": "https://www.vinted.fr/catalog",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
    }

    data = scrapfly_session_then_api(
        session_url="https://www.vinted.fr",
        api_url=api_url,
        api_headers=api_headers,
    )

    if not data:
        logger.warning(f"[Vinted] Pas de données pour '{brand}'")
        return []

    items = data.get("items", [])
    logger.info(f"[Vinted] {len(items)} items bruts pour '{brand}'")

    results = []
    for item in items:
        title = item.get("title", "")
        price_raw = item.get("price")

        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        photo = item.get("photo") or {}
        image = photo.get("url") or photo.get("full_size_url")
        item_id = str(item.get("id", ""))

        size = item.get("size_title", "")
        if not size:
            sz = item.get("size", {})
            if isinstance(sz, dict):
                size = sz.get("title", "") or sz.get("name", "")

        results.append({
            "id": item_id,
            "title": title,
            "price": price,
            "size": size,
            "url": f"https://www.vinted.fr/items/{item_id}",
            "image": image,
            "source": "Vinted",
            "brand": brand,
        })

    logger.info(f"[Vinted] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE
# ──────────────────────────────────────────

def fetch_vestiaire_new(brand: str) -> list:
    logger.info(f"[VC] Recherche '{brand}'...")

    # Utilise l'API GraphQL/REST interne
    url = (
        f"https://www.vestiairecollective.com/api/product/search/v2/"
        f"?keywords={brand.replace(' ', '+')}"
        f"&priceMin={MIN_PRICE}&priceMax={MAX_PRICE}"
        f"&sortBy=new&page=1&pageSize=50&country=FR&currency=EUR"
    )

    headers = {
        "Accept": "application/json",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Origin": "https://www.vestiairecollective.com",
        "Referer": f"https://www.vestiairecollective.com/search/?q={brand.replace(' ', '+')}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "x-market": "FR",
        "x-currency": "EUR",
    }

    content = scrapfly_simple(url, headers=headers)

    if not content:
        logger.warning(f"[VC] Pas de réponse pour '{brand}'")
        return []

    try:
        data = json.loads(content)
    except Exception:
        logger.warning(f"[VC] Réponse non-JSON pour '{brand}'")
        return []

    items = (
        data.get("items", [])
        or data.get("products", [])
        or data.get("results", [])
        or data.get("data", {}).get("items", [])
        or data.get("data", {}).get("products", [])
    )

    logger.info(f"[VC] {len(items)} items bruts pour '{brand}'")

    results = []
    for item in items:
        title = item.get("name", "") or item.get("title", "")
        price_obj = item.get("price", {})

        if isinstance(price_obj, dict):
            cents = price_obj.get("cents")
            price_raw = cents / 100 if cents else (
                price_obj.get("amount") or price_obj.get("value")
            )
        else:
            price_raw = price_obj

        if not title_ok(title, brand) or not price_ok(price_raw):
            continue

        price = parse_price(price_raw)
        link = item.get("url", "") or item.get("link", "")
        if link and not link.startswith("http"):
            link = "https://www.vestiairecollective.com" + link

        image = None
        pics = item.get("pictures", []) or item.get("images", [])
        if pics:
            first = pics[0]
            image = first.get("url") if isinstance(first, dict) else first
        elif item.get("picture"):
            pic = item["picture"]
            image = pic.get("url") if isinstance(pic, dict) else pic

        size_str = ""
        size = item.get("size", {})
        if isinstance(size, dict):
            size_str = size.get("name", "") or size.get("title", "")
        elif isinstance(size, str):
            size_str = size

        results.append({
            "id": str(item.get("id", link)),
            "title": title,
            "price": price,
            "size": size_str,
            "url": link,
            "image": image,
            "source": "Vestiaire Collective",
            "brand": brand,
        })

    logger.info(f"[VC] {len(results)} articles valides pour '{brand}'")
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
