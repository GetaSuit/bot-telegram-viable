import time
import random
import logging
import requests
from config import MIN_PRICE, MAX_PRICE, HARD_EXCLUDES

logger = logging.getLogger(__name__)

MAX_PER_SOURCE = 20

# Session Vinted persistante
VINTED_SESSION = requests.Session()
VINTED_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.vinted.fr",
    "Referer": "https://www.vinted.fr/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
})


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

def init_vinted_session():
    """Initialise les cookies Vinted."""
    try:
        r = VINTED_SESSION.get(
            "https://www.vinted.fr",
            timeout=10,
            allow_redirects=True,
        )
        logger.info(f"[Vinted] Session init: {r.status_code}")
        time.sleep(1)
        # Récupère le token CSRF si présent
        VINTED_SESSION.get(
            "https://www.vinted.fr/api/v2/configurations",
            timeout=10,
        )
        return True
    except Exception as e:
        logger.error(f"[Vinted] Init: {e}")
        return False


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

def fetch_vinted_new(brand: str) -> list:
    logger.info(f"[Vinted] Recherche '{brand}'...")
    results = []

    try:
        init_vinted_session()

        params = {
            "search_text": brand,
            "price_from": MIN_PRICE,
            "price_to": MAX_PRICE,
            "currency": "EUR",
            "per_page": 50,
            "page": 1,
            "order": "newest_first",
        }

        r = VINTED_SESSION.get(
            "https://www.vinted.fr/api/v2/catalog/items",
            params=params,
            timeout=15,
        )

        logger.info(f"[Vinted] Status: {r.status_code}")

        if r.status_code == 401 or r.status_code == 403:
            logger.warning(f"[Vinted] Bloqué ({r.status_code}) — réinit session")
            init_vinted_session()
            r = VINTED_SESSION.get(
                "https://www.vinted.fr/api/v2/catalog/items",
                params=params,
                timeout=15,
            )

        if r.status_code != 200:
            logger.warning(f"[Vinted] Status final: {r.status_code}")
            return []

        try:
            data = r.json()
        except Exception:
            logger.warning("[Vinted] Réponse non-JSON")
            return []

        items = data.get("items", [])
        logger.info(f"[Vinted] {len(items)} items bruts")

        for item in items:
            title = item.get("title", "")
            price_raw = item.get("price")

            if not title_ok(title, brand) or not price_ok(price_raw):
                continue

            price = parse_price(price_raw)
            photo = item.get("photo") or {}
            image = photo.get("url") or photo.get("full_size_url")
            item_id = str(item.get("id", ""))

            # Taille
            size = item.get("size_title", "")
            if not size:
                sz = item.get("size", {})
                if isinstance(sz, dict):
                    size = sz.get("title", "") or sz.get("name", "")
                elif isinstance(sz, str):
                    size = sz

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

    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")

    logger.info(f"[Vinted] {len(results)} articles valides pour '{brand}'")
    return results


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE
# ──────────────────────────────────────────

def fetch_vestiaire_new(brand: str) -> list:
    logger.info(f"[VC] Recherche '{brand}'...")
    results = []

    try:
        # API search Vestiaire
        params = {
            "q": brand,
            "priceMin": MIN_PRICE,
            "priceMax": MAX_PRICE,
            "sortBy": "new",
            "page": 1,
            "pageSize": 50,
            "country": "FR",
            "currency": "EUR",
        }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Accept-Language": "fr-FR,fr;q=0.9",
            "Referer": f"https://www.vestiairecollective.com/search/?q={brand.replace(' ', '+')}",
            "Origin": "https://www.vestiairecollective.com",
            "x-market": "FR",
            "x-currency": "EUR",
        }

        r = requests.get(
            "https://www.vestiairecollective.com/api/product/search/v2/",
            params=params,
            headers=headers,
            timeout=15,
        )

        logger.info(f"[VC] Status: {r.status_code}")

        if r.status_code != 200:
            logger.warning(f"[VC] Échec API principale")
            return []

        try:
            data = r.json()
        except Exception:
            logger.warning("[VC] Réponse non-JSON")
            return []

        items = (
            data.get("items", [])
            or data.get("products", [])
            or data.get("results", [])
            or data.get("data", {}).get("items", [])
        )

        logger.info(f"[VC] {len(items)} items bruts")

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

    except Exception as e:
        logger.error(f"[VC] Erreur '{brand}': {e}")

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
