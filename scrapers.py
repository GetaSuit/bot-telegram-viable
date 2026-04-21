import requests
import time
import random
import logging
from datetime import datetime, timezone
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    EBAY_APP_ID, EBAY_CERT_ID,
    TIER1_BRANDS, TIER2_BRANDS, TIER3_BRANDS,
    EXCLUDED_KEYWORDS, ALLOWED_KEYWORDS,
    HYPE_KEYWORDS,
)
from ai_scorer import analyze_article

logger = logging.getLogger(__name__)

# Annonces de plus de 30 jours ignorées
MAX_AGE_DAYS = 30


# ──────────────────────────────────────────
# PRIX
# ──────────────────────────────────────────

def parse_price(price_raw) -> float | None:
    try:
        if isinstance(price_raw, dict):
            val = price_raw.get("amount") or price_raw.get("value", "")
        else:
            val = price_raw
        return float(str(val).replace(",", ".").replace("€", "").replace(" ", "").strip())
    except Exception:
        return None

def price_ok(price_raw) -> bool:
    price = parse_price(price_raw)
    if price is None:
        return False
    return MIN_PRICE <= price <= MAX_PRICE


# ──────────────────────────────────────────
# DATE
# ──────────────────────────────────────────

def is_recent(timestamp: int) -> bool:
    """Retourne True si l'annonce a moins de MAX_AGE_DAYS jours."""
    if not timestamp:
        return True  # si pas de date, on laisse passer
    try:
        item_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        days_old = (datetime.now(tz=timezone.utc) - item_date).days
        return days_old <= MAX_AGE_DAYS
    except Exception:
        return True


# ──────────────────────────────────────────
# DÉTECTEUR COUP DU JOUR
# ──────────────────────────────────────────

def is_hype(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in HYPE_KEYWORDS)


# ──────────────────────────────────────────
# SCORE TECHNIQUE (0–100)
# ──────────────────────────────────────────

def compute_base_score(item: dict, brand: str) -> int:
    score = 0
    title = (item.get("title") or "").lower()
    price = parse_price(item.get("price"))

    if brand.lower() in title:
        score += 25
    for kw in ALLOWED_KEYWORDS:
        if kw.lower() in title:
            score += 20
            break
    if is_hype(title):
        score += 15
    if price is not None:
        if MIN_PRICE <= price <= 150:
            score += 15
        elif 150 < price <= 250:
            score += 10
        elif 250 < price <= MAX_PRICE:
            score += 5
    if item.get("source") == "eBay":
        score += 10
    elif item.get("source") == "Vinted":
        score += 5
    if item.get("image"):
        score += 5
    if len(title) < 20:
        score -= 10

    return max(0, min(100, score))


# ──────────────────────────────────────────
# FILTRE PERTINENCE
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
    if not title or not brand:
        return False
    title_lower = title.lower()
    if brand.lower() not in title_lower:
        return False
    for kw in EXCLUDED_KEYWORDS:
        if kw.lower() in title_lower:
            return False
    for kw in ALLOWED_KEYWORDS:
        if kw.lower() in title_lower:
            return True
    return False


# ──────────────────────────────────────────
# EBAY
# ──────────────────────────────────────────

def get_ebay_token():
    import base64
    credentials = base64.b64encode(
        f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()
    ).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
        timeout=10,
    )
    return r.json().get("access_token")

def search_ebay(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        token = get_ebay_token()
        if not token:
            logger.error("[eBay] Token introuvable")
            return []

        # Date limite : articles des 30 derniers jours
        date_limit = datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")
        cutoff = datetime.now(tz=timezone.utc).replace(
            day=datetime.now().day - MAX_AGE_DAYS
            if datetime.now().day > MAX_AGE_DAYS else 1
        )

        for category in ["veste blazer", "manteau coat", "sac bag"]:
            params = {
                "q": f"{brand} {category}",
                "filter": (
                    f"price:[{min_price}..{max_price}],"
                    f"currency:EUR,"
                    f"itemLocationCountry:FR"
                ),
                "sort": "newlyListed",
                "limit": 20,
            }
            r = requests.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=15,
            )
            r.raise_for_status()

            for item in r.json().get("itemSummaries", []):
                title = item.get("title", "")
                price_raw = item.get("price", {})

                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue

                # Filtre date eBay via itemCreationDate
                item_date_str = item.get("itemCreationDate", "")
                if item_date_str:
                    try:
                        item_date = datetime.fromisoformat(
                            item_date_str.replace("Z", "+00:00")
                        )
                        days_old = (datetime.now(tz=timezone.utc) - item_date).days
                        if days_old > MAX_AGE_DAYS:
                            logger.debug(f"[eBay] Trop ancien ({days_old}j): {title}")
                            continue
                    except Exception:
                        pass

                parsed_price = parse_price(price_raw)
                result = {
                    "title": title,
                    "price": parsed_price,
                    "url": item.get("itemWebUrl"),
                    "image": item.get("image", {}).get("imageUrl"),
                    "source": "eBay",
                    "description": "",
                }

                base = compute_base_score(result, brand)

                if base > 80:
                    ai = analyze_article(
                        title=title,
                        brand=brand,
                        price=parsed_price or 0,
                        source="eBay",
                    )
                    if not ai.get("is_authentic", True):
                        logger.info(f"[eBay] Suspect ignoré: {title}")
                        continue
                    result["ai_score"] = ai.get("ai_score", 50)
                    result["is_trending"] = ai.get("is_trending", False)
                    result["ai_verdict"] = ai.get("verdict", "correct")
                    result["ai_reason"] = ai.get("reason", "")
                    result["is_hype"] = is_hype(title) or ai.get("is_trending", False)
                    result["score"] = min(100, int(base * 0.4 + ai.get("ai_score", 50) * 0.6))
                else:
                    result["ai_score"] = 50
                    result["is_trending"] = False
                    result["ai_verdict"] = "correct"
                    result["ai_reason"] = ""
                    result["is_hype"] = is_hype(title)
                    result["score"] = base

                results.append(result)

            time.sleep(0.5)

        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        unique.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[eBay] {len(unique)} résultats pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[eBay] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# VINTED
# ──────────────────────────────────────────

VINTED_SESSION = requests.Session()
VINTED_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
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

def _vinted_init_session():
    try:
        VINTED_SESSION.get(
            "https://www.vinted.fr",
            timeout=10,
            allow_redirects=True,
        )
        VINTED_SESSION.get(
            "https://www.vinted.fr/api/v2/configurations",
            timeout=10,
        )
        return True
    except Exception as e:
        logger.error(f"[Vinted] Init session: {e}")
        return False

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE):
    results = []
    try:
        _vinted_init_session()

        for category in ["veste blazer", "manteau", "sac"]:
            params = {
                "search_text": f"{brand} {category}",
                "price_from": min_price,
                "price_to": max_price,
                "currency": "EUR",
                "per_page": 20,
                "order": "newest_first",
            }
            r = VINTED_SESSION.get(
                "https://www.vinted.fr/api/v2/catalog/items",
                params=params,
                timeout=15,
            )
            r.raise_for_status()

            for item in r.json().get("items", []):
                title = item.get("title", "")
                price_raw = item.get("price")
                desc = item.get("description", "") or ""

                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue

                # Filtre date Vinted
                timestamp = item.get("updated_at_ts") or item.get("created_at_ts", 0)
                if timestamp and not is_recent(timestamp):
                    logger.debug(f"[Vinted] Trop ancien: {title}")
                    continue

                parsed_price = parse_price(price_raw)
                photo = item.get("photo") or {}
                result = {
                    "title": title,
                    "price": parsed_price,
                    "url": f"https://www.vinted.fr/items/{item.get('id')}",
                    "image": photo.get("url"),
                    "source": "Vinted",
                    "description": desc,
                }

                base = compute_base_score(result, brand)

                if base > 80:
                    ai = analyze_article(
                        title=title,
                        brand=brand,
                        price=parsed_price or 0,
                        source="Vinted",
                    )
                    if not ai.get("is_authentic", True):
                        logger.info(f"[Vinted] Suspect ignoré: {title}")
                        continue
                    result["ai_score"] = ai.get("ai_score", 50)
                    result["is_trending"] = ai.get("is_trending", False)
                    result["ai_verdict"] = ai.get("verdict", "correct")
                    result["ai_reason"] = ai.get("reason", "")
                    result["is_hype"] = is_hype(title, desc) or ai.get("is_trending", False)
                    result["score"] = min(100, int(base * 0.4 + ai.get("ai_score", 50) * 0.6))
                else:
                    result["ai_score"] = 50
                    result["is_trending"] = False
                    result["ai_verdict"] = "correct"
                    result["ai_reason"] = ""
                    result["is_hype"] = is_hype(title, desc)
                    result["score"] = base

                results.append(result)

            time.sleep(random.uniform(1.0, 2.0))

        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        unique.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"[Vinted] {len(unique)} résultats pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def search_all_sources(brand: str):
    all_results = []
    all_results.extend(search_ebay(brand))
    all_results.extend(search_vinted(brand))
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results
