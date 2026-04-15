"""
scrapers.py — Version robuste avec APIs publiques
eBay RSS · Vestiaire · Leboncoin
"""

import re
import time
import random
import logging
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from config import SIZES_MEN, SIZES_WOMEN

log = logging.getLogger(__name__)

ALL_SIZES = SIZES_MEN + SIZES_WOMEN

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
#  EBAY — via flux RSS public (très stable, jamais bloqué)
# ─────────────────────────────────────────────────────────────────

def scrape_ebay(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        # eBay RSS feed — API publique qui ne bloque jamais
        url = "https://www.ebay.fr/sch/i.html"
        params = {
            "_nkw": brand,
            "_sacat": "0",
            "_udhi": max_price,
            "_sop": "10",  # plus récents en premier
            "LH_ItemCondition": "1000|1500|2000|2500",
            "_rss": "1",  # format RSS
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)

        if resp.status_code == 200 and "<rss" in resp.text:
            # Parser le RSS
            root = ET.fromstring(resp.text)
            ns = {"ebay": "urn:ebay:apis:eBLBaseComponents"}
            for item in root.findall(".//item")[:20]:
                title = item.findtext("title", "")
                link  = item.findtext("link", "")
                desc  = item.findtext("description", "")

                # Extraire le prix depuis la description
                price_match = re.search(r"(\d+[.,]\d+)\s*EUR", desc)
                if not price_match:
                    price_match = re.search(r"EUR\s*(\d+[.,]\d+)", desc)
                if not price_match:
                    continue
                price = _parse_price(price_match.group(1))
                if not price or price > max_price:
                    continue

                # Extraire l'image
                img_match = re.search(r'src="(https://i\.ebayimg[^"]+)"', desc)
                image_url = img_match.group(1) if img_match else ""

                results.append({
                    "title":       title,
                    "price":       price,
                    "url":         link,
                    "image_url":   image_url,
                    "brand":       brand,
                    "size":        "",
                    "description": title,
                    "platform":    "eBay",
                })
        else:
            # Fallback HTML classique
            params.pop("_rss", None)
            resp2 = requests.get(url, params=params, headers=HEADERS, timeout=15)
            soup  = BeautifulSoup(resp2.text, "html.parser")
            for item in soup.select(".s-item")[:20]:
                title_el = item.select_one(".s-item__title")
                price_el = item.select_one(".s-item__price")
                link_el  = item.select_one("a.s-item__link")
                img_el   = item.select_one("img")
                if not all([title_el, price_el, link_el]):
                    continue
                if "Shop on eBay" in (title_el.text or ""):
                    continue
                price = _parse_price(price_el.text)
                if not price or price > max_price:
                    continue
                image_url = ""
                if img_el:
                    image_url = img_el.get("src") or img_el.get("data-src", "")
                    if "gif" in image_url or "spinner" in image_url:
                        image_url = img_el.get("data-src", "")
                results.append({
                    "title":       title_el.text.strip(),
                    "price":       price,
                    "url":         link_el["href"].split("?")[0],
                    "image_url":   image_url,
                    "brand":       brand,
                    "size":        "",
                    "description": title_el.text.strip(),
                    "platform":    "eBay",
                })
    except Exception as e:
        log.error(f"eBay error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  VESTIAIRE COLLECTIVE — scraping HTML
# ─────────────────────────────────────────────────────────────────

def scrape_vestiaire(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = f"https://www.vestiairecollective.com/search/?q={requests.utils.quote(brand)}&order=new&priceMax={max_price}"
        headers = {**HEADERS, "Accept": "text/html,application/xhtml+xml,*/*"}
        resp = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("[class*='productCard'], [class*='product-card'], article")[:20]:
            title_el = card.select_one("[class*='name'], [class*='title'], h2, h3")
            price_el = card.select_one("[class*='price']")
            link_el  = card.select_one("a[href]")
            img_el   = card.select_one("img")

            if not link_el:
                continue

            title = title_el.text.strip() if title_el else brand
            price = _parse_price(price_el.text) if price_el else None
            if not price or price > max_price:
                continue

            href = link_el.get("href", "")
            full_url = href if href.startswith("http") else f"https://www.vestiairecollective.com{href}"
            image_url = ""
            if img_el:
                image_url = img_el.get("src") or img_el.get("data-src", "")

            results.append({
                "title":       title,
                "price":       price,
                "url":         full_url,
                "image_url":   image_url,
                "brand":       brand,
                "size":        "",
                "description": title,
                "platform":    "Vestiaire Collective",
            })
    except Exception as e:
        log.error(f"Vestiaire error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  LEBONCOIN — API interne JSON
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
            data = resp.json()
            for ad in data.get("ads", [])[:20]:
                price = ad.get("price", [None])[0] if ad.get("price") else None
                if not price or price > max_price:
                    continue
                ad_id    = ad.get("list_id", "")
                slug     = ad.get("slug", "")
                full_url = f"https://www.leboncoin.fr/ventes_immobilieres/{ad_id}.htm"
                if slug:
                    full_url = f"https://www.leboncoin.fr/{slug}"
                images   = ad.get("images", {})
                img_list = images.get("urls", []) if isinstance(images, dict) else []
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
            params   = {"text": brand, "category": "2", "price": f"0-{max_price}", "shippable": "1"}
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
                href     = card.get("href", "")
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
    results += scrape_vestiaire(brand, max_price)
    results += scrape_leboncoin(brand, max_price)
    return results
