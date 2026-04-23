import os
import requests
import time
import random
import logging
import json
import re
from config import (
    BRANDS, MIN_PRICE, MAX_PRICE,
    HYPE_KEYWORDS,
)
from ai_scorer import analyze_article

logger = logging.getLogger(__name__)

MAX_ARTICLES_PER_SOURCE = 10
SCRAPFLY_KEY = os.environ.get("SCRAPFLY_KEY", "")


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
# HYPE
# ──────────────────────────────────────────

def is_hype(title: str, description: str = "") -> bool:
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in HYPE_KEYWORDS)


# ──────────────────────────────────────────
# FILTRE MINIMAL
# ──────────────────────────────────────────

def is_relevant(title: str, brand: str) -> bool:
    if not title or not brand:
        return False
    title_lower = title.lower()
    if brand.lower() not in title_lower:
        return False
    hard_excludes = [
        "parfum", "perfume", "cologne", "eau de",
        "iphone", "samsung", "ordinateur", "laptop",
        "voiture", "moto", "vélo", "jouet", "toy",
        "livre", "book", "dvd",
    ]
    for kw in hard_excludes:
        if kw in title_lower:
            return False
    return True


# ──────────────────────────────────────────
# VINTED via ScrapFly
# ──────────────────────────────────────────

def search_vinted(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE,
                  max_articles=MAX_ARTICLES_PER_SOURCE):
    if not SCRAPFLY_KEY:
        logger.warning("[Vinted] SCRAPFLY_KEY manquante")
        return []

    results = []
    candidates = []

    try:
        for page in range(1, 4):
            vinted_url = (
                f"https://www.vinted.fr/catalog?"
                f"search_text={brand.replace(' ', '+')}"
                f"&price_from={min_price}"
                f"&price_to={max_price}"
                f"&currency=EUR"
                f"&page={page}"
                f"&order=relevance"
            )

            r = requests.get(
                "https://api.scrapfly.io/scrape",
                params={
                    "key": SCRAPFLY_KEY,
                    "url": vinted_url,
                    "asp": "true",
                    "render_js": "true",
                    "country": "fr",
                },
                timeout=30,
            )

            if r.status_code != 200:
                logger.warning(f"[Vinted] ScrapFly status {r.status_code}")
                break

            html = r.json().get("result", {}).get("content", "")
            if not html:
                logger.warning(f"[Vinted] Contenu vide page {page}")
                break

            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            if not match:
                logger.warning(f"[Vinted] __NEXT_DATA__ introuvable page {page}")
                break

            try:
                next_data = json.loads(match.group(1))
                page_props = next_data.get("props", {}).get("pageProps", {})
                logger.info(f"[Vinted] pageProps keys: {list(page_props.keys())[:10]}")

                items = (
                    page_props.get("catalogItems", {}).get("catalogItems", [])
                    or page_props.get("items", [])
                    or page_props.get("initialState", {}).get("catalog", {}).get("items", [])
                )
                logger.info(f"[Vinted] Items trouvés: {len(items)}")

            except Exception as e:
                logger.warning(f"[Vinted] Parse erreur: {e}")
                break

            if not items:
                break

            for item in items:
                title = item.get("title", "") or item.get("name", "")
                price_raw = item.get("price", {})
                if not price_ok(price_raw):
                    continue
                if not is_relevant(title, brand):
                    continue
                candidates.append(item)

            if len(candidates) >= max_articles * 3:
                break
            time.sleep(1)

        logger.info(f"[Vinted] {len(candidates)} candidats → analyse {min(len(candidates), max_articles)}")

        for item in candidates[:max_articles]:
            title = item.get("title", "") or item.get("name", "")
            price_raw = item.get("price")
            desc = item.get("description", "") or ""
            parsed_price = parse_price(price_raw)
            photo = item.get("photo") or {}
            image_url = photo.get("url") or item.get("image", {}).get("url")
            use_vision = is_hype(title, desc)

            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="Vinted",
                image_url=image_url if use_vision else None,
            )

            if not ai.get("keep", True):
                logger.info(f"[Vinted] Ignoré: {title[:50]}")
                continue

            item_id = item.get("id", "")
            results.append({
                "title": title,
                "price": parsed_price,
                "url": f"https://www.vinted.fr/items/{item_id}",
                "image": image_url,
                "source": "Vinted",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title, desc) or ai.get("is_trending", False),
                "is_runway": ai.get("is_runway", False),
                "collection": ai.get("collection"),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
                "liquidity": ai.get("liquidity", "normale"),
                "risk": ai.get("risk", "moyen"),
            })

        seen = set()
        unique = []
        for item in results:
            if item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        logger.info(f"[Vinted] {len(unique)} articles validés pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[Vinted] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# VESTIAIRE COLLECTIVE via ScrapFly
# ──────────────────────────────────────────

def search_vestiaire(brand: str, min_price=MIN_PRICE, max_price=MAX_PRICE,
                     max_articles=MAX_ARTICLES_PER_SOURCE):
    if not SCRAPFLY_KEY:
        logger.warning("[VC] SCRAPFLY_KEY manquante")
        return []

    results = []
    candidates = []

    try:
        for page in range(1, 4):
            vc_url = (
                f"https://www.vestiairecollective.com/search/"
                f"?q={brand.replace(' ', '+')}"
                f"&priceMin={min_price}"
                f"&priceMax={max_price}"
                f"&page={page}"
            )

            r = requests.get(
                "https://api.scrapfly.io/scrape",
                params={
                    "key": SCRAPFLY_KEY,
                    "url": vc_url,
                    "asp": "true",
                    "render_js": "true",
                    "country": "fr",
                },
                timeout=30,
            )

            if r.status_code != 200:
                logger.warning(f"[VC] ScrapFly status {r.status_code}")
                break

            html = r.json().get("result", {}).get("content", "")
            if not html:
                logger.warning(f"[VC] Contenu vide page {page}")
                break

            match = re.search(
                r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
                html, re.DOTALL
            )
            if not match:
                logger.warning(f"[VC] __NEXT_DATA__ introuvable page {page}")
                break

            try:
                next_data = json.loads(match.group(1))
                page_props = next_data.get("props", {}).get("pageProps", {})
                logger.info(f"[VC] pageProps keys: {list(page_props.keys())[:10]}")

                items = []

                # Structure 1 — dehydratedState (React Query)
                dehydrated = page_props.get("dehydratedState", {})
                if dehydrated:
                    queries = dehydrated.get("queries", [])
                    for query in queries:
                        data = query.get("state", {}).get("data", {})
                        if isinstance(data, dict):
                            potential = (
                                data.get("items", [])
                                or data.get("products", [])
                                or data.get("results", [])
                            )
                            if potential:
                                items = potential
                                break

                # Structure 2 — pageProps directs
                if not items:
                    items = (
                        page_props.get("initialData", {}).get("items", [])
                        or page_props.get("search", {}).get("items", [])
                        or page_props.get("products", [])
                        or page_props.get("items", [])
                    )

                logger.info(f"[VC] Items trouvés: {len(items)}")

            except Exception as e:
                logger.warning(f"[VC] Parsing JSON: {e}")
                break

            if not items:
                logger.info(f"[VC] Aucun article page {page}")
                break

            for item in items:
                try:
                    price_obj = item.get("price", {})
                    if isinstance(price_obj, dict):
                        price_raw = price_obj.get("cents", 0) / 100
                    else:
                        price_raw = price_obj

                    if not price_raw or not price_ok(price_raw):
                        continue

                    title = item.get("name", "") or item.get("title", "")
                    if not is_relevant(title, brand):
                        continue

                    link = item.get("link", item.get("url", ""))
                    image = None
                    if item.get("pictures"):
                        image = item["pictures"][0].get("url")
                    elif item.get("picture"):
                        image = item["picture"].get("url")

                    candidates.append({
                        "title": title,
                        "price": parse_price(price_raw),
                        "url": (
                            "https://www.vestiairecollective.com" + link
                            if link.startswith("/") else link
                        ),
                        "image": image,
                    })
                except Exception:
                    continue

            if len(candidates) >= max_articles * 3:
                break
            time.sleep(2)

        logger.info(f"[VC] {len(candidates)} candidats → analyse {min(len(candidates), max_articles)}")

        for item in candidates[:max_articles]:
            title = item.get("title", "")
            parsed_price = item.get("price")
            image_url = item.get("image")
            use_vision = is_hype(title)

            ai = analyze_article(
                title=title,
                brand=brand,
                price=parsed_price or 0,
                source="Vestiaire Collective",
                image_url=image_url if use_vision else None,
            )

            if not ai.get("keep", True):
                logger.info(f"[VC] Ignoré: {title[:50]}")
                continue

            results.append({
                "title": title,
                "price": parsed_price,
                "url": item.get("url"),
                "image": image_url,
                "source": "Vestiaire Collective",
                "is_trending": ai.get("is_trending", False),
                "is_hype": is_hype(title) or ai.get("is_trending", False),
                "is_runway": ai.get("is_runway", False),
                "collection": ai.get("collection"),
                "ai_verdict": ai.get("verdict", "correct"),
                "ai_reason": ai.get("reason", ""),
                "market_value": ai.get("market_value"),
                "liquidity": ai.get("liquidity", "normale"),
                "risk": ai.get("risk", "moyen"),
            })

        seen = set()
        unique = []
        for item in results:
            if item.get("url") and item["url"] not in seen:
                seen.add(item["url"])
                unique.append(item)

        logger.info(f"[VC] {len(unique)} articles validés pour '{brand}'")
        return unique

    except Exception as e:
        logger.error(f"[VC] Erreur '{brand}': {e}")
        return []


# ──────────────────────────────────────────
# UNIFIÉ
# ──────────────────────────────────────────

def search_all_sources(brand: str, max_articles=MAX_ARTICLES_PER_SOURCE):
    all_results = []
    all_results.extend(search_vinted(brand, max_articles=max_articles))
    all_results.extend(search_vestiaire(brand, max_articles=max_articles))
    return all_results
