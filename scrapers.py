"""
scrapers.py — eBay API officielle + Vestiaire Collective
"""

import re
import json
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from config import SIZES_MEN, SIZES_WOMEN

log = logging.getLogger(__name__)

EBAY_APP_ID = "FlorianB-SOURCELU-PRD-c6c21b7a2-f7ba2d0e"

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


# ─────────────────────────────────────────────────────────────────
#  EBAY — API Finding officielle (jamais bloquée)
# ─────────────────────────────────────────────────────────────────

def scrape_ebay(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = "https://svcs.ebay.com/services/search/FindingService/v1"
        params = {
            "OPERATION-NAME":          "findItemsAdvanced",
            "SERVICE-VERSION":         "1.0.0",
            "SECURITY-APPNAME":        EBAY_APP_ID,
            "RESPONSE-DATA-FORMAT":    "JSON",
            "REST-PAYLOAD":            "",
            "keywords":                brand,
            "categoryId":              "11450",  # Vêtements
            "itemFilter(0).name":      "MaxPrice",
            "itemFilter(0).value":     str(max_price),
            "itemFilter(0).paramName": "Currency",
            "itemFilter(0).paramValue":"EUR",
            "itemFilter(1).name":      "ListingType",
            "itemFilter(1).value":     "FixedPrice",
            "itemFilter(2).name":      "Condition",
            "itemFilter(2).value(0)":  "1000",
            "itemFilter(2).value(1)":  "1500",
            "itemFilter(2).value(2)":  "2000",
            "itemFilter(2).value(3)":  "2500",
            "sortOrder":               "StartTimeNewest",
            "paginationInput.entriesPerPage": "20",
            "outputSelector(0)":       "PictureURLLarge",
            "outputSelector(1)":       "GalleryInfo",
            "affiliate.networkId":     "9",
            "affiliate.siteId":        "71",
            "siteid":                  "71",
        }

        resp = requests.get(url, params=params, timeout=15)
        data = resp.json()

        search_result = (
            data.get("findItemsAdvancedResponse", [{}])[0]
               .get("searchResult", [{}])[0]
        )
        items = search_result.get("item", [])

        for item in items:
            title     = item.get("title", [""])[0]
            item_url  = item.get("viewItemURL", [""])[0]
            price_raw = item.get("sellingStatus", [{}])[0].get("currentPrice", [{}])[0]
            price     = float(price_raw.get("__value__", 0))

            if not price or price > max_price:
                continue

            # Image
            image_url = ""
            pics = item.get("pictureURLLarge", [])
            if not pics:
                pics = item.get("galleryURL", [])
            if pics:
                image_url = pics[0]

            # Taille depuis le titre
            size = ""
            for s in SIZES_MEN + SIZES_WOMEN:
                if s.upper() in title.upper():
                    size = s
                    break

            results.append({
                "title":       title,
                "price":       price,
                "url":         item_url,
                "image_url":   image_url,
                "brand":       brand,
                "size":        size,
                "description": title,
                "platform":    "eBay",
            })

        log.info(f"eBay '{brand}': {len(results)} articles trouvés")

    except Exception as e:
        log.error(f"eBay API error ({brand}): {e}")
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

        # JSON embarqué
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

        # Fallback HTML
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

        log.info(f"Vestiaire '{brand}': {len(results)} articles trouvés")

    except Exception as e:
        log.error(f"Vestiaire error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  DISPATCHER
# ─────────────────────────────────────────────────────────────────

def scrape_all(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    results += scrape_ebay(brand, max_price)
    results += scrape_vestiaire(brand, max_price)
    return results
