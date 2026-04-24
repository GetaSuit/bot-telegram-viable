import os
import json
import re
import time
import random
import logging
import requests
from config import BRANDS, MIN_PRICE, MAX_PRICE, HARD_EXCLUDES, SCRAPFLY_KEY
from ai_scorer import is_worth_buying

logger = logging.getLogger(__name__)

MAX_PER_SOURCE = 15


# ──────────────────────────────────────────
# UTILITAIRES
# ──────────────────────────────────────────

def parse_price(raw) -> float | None:
    try:
        if isinstance(raw, dict):
            v = raw.get("amount") or raw.get("value") or raw.get("cents", 0)
            if raw.get("cents"):
                return float(v) / 100
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


def scrapfly_get(url: str, render_js: bool = False) -> str | None:
    """Appel ScrapFly avec anti-bot."""
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

        r = requests.get(
            "https://api.scrapfly.io/scrape",
            params=params,
            timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"[ScrapFly] Status {r.status_code} pour {url[:60]}")
            return None
        return r.json().get("result", {}).get("content", "")
    except Exception as e:
        logger.error(f"[ScrapFly] {e}")
        return None


def extract_next_data(html: str) -> dict:
    """Extrait __NEXT_DATA__ d'une page HTML."""
    if not html:
        return {}
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


def build_result(title, price, url, image, source, brand) -> dict | None:
    """Appelle l'IA et retourne l'article si keep=True."""
    ai = is_worth_buying(title, brand, price or 0, source)
    if not ai.get("keep", True):
        logger.info(f"[{source}] Rejeté: {title[:50]}")
        return None

    market_value = ai.get("market_value")
    profit_net = None
    if market_value and price:
        try:
            profit_net = round(float(market_value) - float(price) - float(market_value) * 0.15, 0)
        except Exception:
            pass

    return {
        "title": title,
        "price": price,
        "url": url,
        "image": image,
        "source": source,
        "ai_reason": ai.get("reason", ""),
        "ai_verdict": ai.get("verdict", "correct"),
        "market_value": market_value,
        "profit_net": profit_net,
    }


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

def search_vinted(brand: str) -> list:
    results = []
    logger.info(f"[Vinted] Recherche '{brand}'...")

    for page in range(1, 4):
        url = (
            f"https://www.vinted.fr/catalog"
            f"?search_text={brand.replace(' ', '+')}"
            f"&price_from={MIN_PRICE}&price_to={MAX_PRICE}"
            f"&currency=EUR&page={page}&order=newest_first"
        )

        html = scrapfly_get(url, render_js=True)
        if not html:
            break

        nd = extract_next_data(html)
        if not nd:
            logger.warning(f"[Vinted] Pas de __NEXT_DATA__ page {page}")
            break

        # Cherche les items dans plusieurs structures possibles
        page_props = nd.get("props", {}).get("pageProps", {})
        items = []

        # Structure 1 — catalogItems
        ci = page_props.get("catalogItems", {})
        if ci:
            items = ci.get("catalogItems", ci.get("items", []))

        # Structure 2 — items directs
        if not items:
            items = page_props.get("items", [])

        # Structure 3 — initialState
        if not items:
            state = page_props.get("initialState", {})
            items = state.get("catalog", {}).get("items", [])

        # Structure 4 — cherche dans tout le JSON
        if not items:
            raw = json.dumps(nd)
            matches = re.findall(r'"catalogItems":\s*(\[.*?\])', raw, re.DOTALL)
            for m in matches:
                try:
                    items = json.loads(m)
                    if items:
                        break
                except Exception:
                    continue

        logger.info(f"[Vinted] Page {page}: {len(items)} items bruts")

        for item in items:
            title = item.get("title", "")
            price_raw = item.get("price")
            if not title_ok(title, brand) or not price_ok(price_raw):
                continue

            price = parse_price(price_raw)
            photo = item.get("photo") or {}
            image = photo.get("url") or photo.get("full_size_url")
            item_id = item.get("id", "")
            url_item = f"https://www.vinted.fr/items/{item_id}"

            r = build_result(title, price, url_item, image, "Vinted", brand)
            if r:
                results.append(r)
                if len(results) >= MAX_PER_SOURCE:
                    return results

        time.sleep(random.uniform(1, 2))

    logger.info(f"[Vinted] {len(results)} articles retenus pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE
# ──────────────────────────────────────────

def search_vestiaire(brand: str) -> list:
    results = []
    logger.info(f"[VC] Recherche '{brand}'...")

    for page in range(1, 4):
        url = (
            f"https://www.vestiairecollective.com/search/"
            f"?q={brand.replace(' ', '+')}"
            f"&priceMin={MIN_PRICE}&priceMax={MAX_PRICE}&page={page}"
        )

        html = scrapfly_get(url, render_js=True)
        if not html:
            break

        nd = extract_next_data(html)
        if not nd:
            logger.warning(f"[VC] Pas de __NEXT_DATA__ page {page}")
            break

        page_props = nd.get("props", {}).get("pageProps", {})
        items = []

        # Structure 1 — dehydratedState (React Query)
        dehydrated = page_props.get("dehydratedState", {})
        if dehydrated:
            for query in dehydrated.get("queries", []):
                data = query.get("state", {}).get("data", {})
                if isinstance(data, dict):
                    for key in ["items", "products", "results", "catalogItems"]:
                        candidate = data.get(key, [])
                        if candidate and isinstance(candidate, list):
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
                matches = re.findall(pattern, raw, re.DOTALL)
                for m in matches:
                    try:
                        candidate = json.loads(m)
                        if candidate and len(candidate) > 2:
                            items = candidate
                            break
                    except Exception:
                        continue
                if items:
                    break

        logger.info(f"[VC] Page {page}: {len(items)} items bruts")

        for item in items:
            title = item.get("name", "") or item.get("title", "")
            price_obj = item.get("price", {})

            if isinstance(price_obj, dict):
                cents = price_obj.get("cents")
                if cents:
                    price_raw = cents / 100
                else:
                    price_raw = price_obj.get("amount") or price_obj.get("value")
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

            r = build_result(title, price, link, image, "Vestiaire Collective", brand)
            if r:
                results.append(r)
                if len(results) >= MAX_PER_SOURCE:
                    return results

        time.sleep(random.uniform(1.5, 2.5))

    logger.info(f"[VC] {len(results)} articles retenus pour '{brand}'")
    return results


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def search_all(brand: str) -> list:
    all_results = []
    all_results.extend(search_vinted(brand))
    all_results.extend(search_vestiaire(brand))
    return all_results
