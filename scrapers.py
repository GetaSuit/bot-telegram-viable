"""
scrapers.py — eBay Browse API avec App ID + Cert ID
"""

import re
import json
import os
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from config import SIZES_MEN, SIZES_WOMEN

log = logging.getLogger(__name__)

EBAY_APP_ID  = os.environ.get("EBAY_APP_ID",  "")
EBAY_CERT_ID = os.environ.get("EBAY_CERT_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def _sleep():
    time.sleep(random.uniform(1.0, 2.0))

def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.,]", "", str(text)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None

_ebay_token = None
_ebay_token_expiry = 0

def get_ebay_token() -> str | None:
    global _ebay_token, _ebay_token_expiry
    if _ebay_token and time.time() < _ebay_token_expiry:
        return _ebay_token
    try:
        import base64
        credentials = base64.b64encode(
            f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()
        ).decode()
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope",
            timeout=15,
        )
        if resp.status_code == 200:
            _ebay_token = resp.json().get("access_token")
            _ebay_token_expiry = time.time() + 6000
            log.info("Token eBay obtenu ✅")
            return _ebay_token
        log.error(f"eBay token error: {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        log.error(f"eBay token exception: {e}")
    return None


# ─────────────────────────────────────────────────────────────────
#  EBAY — Browse API REST
# ─────────────────────────────────────────────────────────────────

def scrape_ebay(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        token = get_ebay_token()
        if not token:
            return []

        url = "https://api.ebay.com/buy/browse/v1/item_summary/search"
        params = {
            "q":            brand,
            "category_ids": "11450",
            "filter":       f"price:[..{max_price}],currency:EUR",
            "sort":         "newlyListed",
            "limit":        "20",
        }
        headers = {
            "Authorization":           f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_FR",
            "Content-Type":            "application/json",
        }
        resp = requests.get(url, params=params, headers=headers, timeout=15)

        if resp.status_code == 200:
            items = resp.json().get("itemSummaries", [])
            for item in items:
                price = float(item.get("price", {}).get("value", 0))
                if not price or price > max_price:
                    continue
                title     = item.get("title", "")
                image_url = item.get("image", {}).get("imageUrl", "")
                size = ""
                for s in SIZES_MEN + SIZES_WOMEN:
                    if s.upper() in title.upper():
                        size = s
                        break
                results.append({
                    "title":       title,
                    "price":       price,
                    "url":         item.get("itemWebUrl", ""),
                    "image_url":   image_url,
                    "brand":       brand,
                    "size":        size,
                    "description": title,
                    "platform":    "eBay",
                })
        else:
            log.error(f"eBay {brand}: {resp.status_code} {resp.text[:200]}")

        log.info(f"eBay '{brand}': {len(results)} articles")

    except Exception as e:
        log.error(f"eBay error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  VESTIAIRE COLLECTIVE
# ─────────────────────────────────────────────────────────────────

def scrape_vestiaire(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = f"https://www.vestiairecollective.com/search/?q={requests.utils.quote(brand)}&order=new&priceMax={max_price}&currency=EUR"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        for script in soup.find_all("script"):
            txt = script.string or ""
            if '"price"' in txt and '"link"' in txt:
                try:
                    match = re.search(r'"items"\s*:\s*(\[.+?\])\s*[,}]', txt, re.DOTALL)
                    if not match:
                        match = re.search(r'"products"\s*:\s*(\[.+?\])\s*[,}]', txt, re.DOTALL)
                    if match:
                        items = json.loads(match.group(1))
                        for item in items[:20]:
                            price_data = item.get("price", {})
                            price = float(price_data.get("cents", 0)) / 100 if isinstance(price_data, dict) else float(price_data or 0)
                            if not price or price > max_price:
                                continue
                            link = item.get("link", item.get("url", ""))
                            full_url = f"https://www.vestiairecollective.com{link}" if link.startswith("/") else link
                            pics = item.get("pictures", item.get("images", []))
                            image_url = pics[0].get("src", "") if pics and isinstance(pics[0], dict) else (pics[0] if pics else "")
                            results.append({
                                "title":       item.get("name", brand),
                                "price":       price,
                                "url":         full_url,
                                "image_url":   image_url,
                                "brand":       brand,
                                "size":        item.get("size", {}).get("name", "") if isinstance(item.get("size"), dict) else "",
                                "description": item.get("name", ""),
                                "platform":    "Vestiaire Collective",
                            })
                except Exception:
                    continue

        if not results:
            for card in soup.select("article, [class*='productCard'], [class*='product-card']")[:20]:
                link_el  = card.select_one("a[href]")
                price_el = card.select_one("[class*='price'], [class*='Price']")
                title_el = card.select_one("[class*='name'], [class*='title'], h2, h3")
                img_el   = card.select_one("img")
                if not link_el or not price_el:
                    continue
                price = _parse_price(price_el.text)
                if not price or price > max_price:
                    continue
                href = link_el.get("href", "")
                full_url = href if href.startswith("http") else f"https://www.vestiairecollective.com{href}"
                results.append({
                    "title":       title_el.text.strip() if title_el else brand,
                    "price":       price,
                    "url":         full_url,
                    "image_url":   img_el.get("src") or img_el.get("data-src", "") if img_el else "",
                    "brand":       brand,
                    "size":        "",
                    "description": title_el.text.strip() if title_el else "",
                    "platform":    "Vestiaire Collective",
                })

        log.info(f"Vestiaire '{brand}': {len(results)} articles")

    except Exception as e:
        log.error(f"Vestiaire error ({brand}): {e}")
    _sleep()
    return results



# ─────────────────────────────────────────────────────────────────
#  LEBONCOIN — API JSON interne
# ─────────────────────────────────────────────────────────────────

def scrape_leboncoin(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = "https://api.leboncoin.fr/api/adfinder/v1/search"
        payload = {
            "filters": {
                "category": {"id": "2"},
                "keywords": {"text": brand, "type": "all"},
                "price":    {"max": str(max_price)},
                "shippable": True,
            },
            "sort_by":    "time",
            "sort_order": "desc",
            "limit":      20,
            "offset":     0,
        }
        headers = {
            **HEADERS,
            "Content-Type": "application/json",
            "api_key":      "ba0c2dad52b3585c9a20cd59d9e66f9e",
            "Origin":       "https://www.leboncoin.fr",
            "Referer":      "https://www.leboncoin.fr/",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)

        if resp.status_code == 200:
            for ad in resp.json().get("ads", [])[:20]:
                price = ad.get("price", [None])[0] if ad.get("price") else None
                if not price or float(price) > max_price:
                    continue
                ad_id    = ad.get("list_id", "")
                slug     = ad.get("slug", "")
                full_url = f"https://www.leboncoin.fr/{slug}" if slug else f"https://www.leboncoin.fr/annonce/{ad_id}"
                images   = ad.get("images", {})
                img_list = images.get("urls_large", images.get("urls", [])) if isinstance(images, dict) else []
                image_url = img_list[0] if img_list else ""
                results.append({
                    "title":       ad.get("subject", ""),
                    "price":       float(price),
                    "url":         full_url,
                    "image_url":   image_url,
                    "brand":       brand,
                    "size":        "",
                    "description": ad.get("body", ""),
                    "platform":    "Leboncoin",
                })
        else:
            # Fallback HTML
            html_url = "https://www.leboncoin.fr/recherche"
            params = {"text": brand, "category": "2", "price": f"0-{max_price}", "shippable": "1"}
            r2   = requests.get(html_url, params=params, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r2.text, "html.parser")
            for card in soup.select("a[data-test-id='ad'], [data-qa-id='aditem_container']")[:20]:
                title_el = card.select_one("[data-test-id='ad-title'], [data-qa-id='aditem_title']")
                price_el = card.select_one("[data-test-id='price'], [data-qa-id='aditem_price']")
                img_el   = card.select_one("img")
                if not title_el or not price_el:
                    continue
                price = _parse_price(price_el.text)
                if not price or price > max_price:
                    continue
                href = card.get("href", "")
                full_url = href if href.startswith("http") else f"https://www.leboncoin.fr{href}"
                results.append({
                    "title":       title_el.text.strip(),
                    "price":       price,
                    "url":         full_url,
                    "image_url":   img_el.get("src", "") if img_el else "",
                    "brand":       brand,
                    "size":        "",
                    "description": title_el.text.strip(),
                    "platform":    "Leboncoin",
                })

        log.info(f"Leboncoin '{brand}': {len(results)} articles")

    except Exception as e:
        log.error(f"Leboncoin error ({brand}): {e}")
    _sleep()
    return results

# ─────────────────────────────────────────────────────────────────
#  DISPATCHER
# ─────────────────────────────────────────────────────────────────

def scrape_all(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    results += scrape_ebay(brand, max_price)
    results += scrape_leboncoin(brand, max_price)
    results += scrape_vestiaire(brand, max_price)
    return results
