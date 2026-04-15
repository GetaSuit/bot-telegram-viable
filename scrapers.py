"""
scrapers.py — Vinted · Vestiaire Collective · eBay · Leboncoin
Version corrigée avec authentification Vinted
"""

import re
import time
import random
import logging
import requests
from bs4 import BeautifulSoup
from config import ALL_BRANDS, SIZES_MEN, SIZES_WOMEN

log = logging.getLogger(__name__)

ALL_SIZES = SIZES_MEN + SIZES_WOMEN

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "application/json, text/html, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def _sleep():
    time.sleep(random.uniform(1.5, 3.0))

def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.,]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────
#  VINTED — authentification par cookie de session
# ─────────────────────────────────────────────────────────────────

_vinted_session = None
_vinted_csrf    = None

def _init_vinted_session():
    global _vinted_session, _vinted_csrf
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "fr-FR,fr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        # 1. Charger la page d'accueil pour obtenir les cookies
        r = session.get("https://www.vinted.fr", timeout=15)
        # 2. Extraire le CSRF token
        csrf = None
        for cookie in session.cookies:
            if "csrf" in cookie.name.lower():
                csrf = cookie.value
                break
        if not csrf:
            m = re.search(r'csrf-token["\s]+content="([^"]+)"', r.text)
            if m:
                csrf = m.group(1)
        session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "X-CSRF-Token": csrf or "",
            "Referer": "https://www.vinted.fr/",
            "Origin": "https://www.vinted.fr",
        })
        _vinted_session = session
        _vinted_csrf    = csrf
        log.info("Session Vinted initialisée")
    except Exception as e:
        log.error(f"Erreur init Vinted: {e}")
        _vinted_session = session

def _get_vinted_session():
    global _vinted_session
    if _vinted_session is None:
        _init_vinted_session()
    return _vinted_session

def scrape_vinted(brand: str, max_price: int = 2000) -> list[dict]:
    session = _get_vinted_session()
    results = []
    try:
        url = "https://www.vinted.fr/api/v2/catalog/items"
        params = {
            "search_text": brand,
            "per_page":    24,
            "page":        1,
            "order":       "newest_first",
            "price_to":    max_price,
        }
        resp = session.get(url, params=params, timeout=15)

        # Si 403, on tente de réinitialiser la session
        if resp.status_code == 403:
            log.warning(f"Vinted 403 pour {brand} — réinitialisation session")
            _init_vinted_session()
            session = _get_vinted_session()
            resp = session.get(url, params=params, timeout=15)

        if resp.status_code != 200:
            log.warning(f"Vinted {brand}: HTTP {resp.status_code}")
            return []

        data = resp.json()
        for item in data.get("items", []):
            price_raw = item.get("price", {})
            price = float(price_raw.get("amount", 0)) if isinstance(price_raw, dict) else 0.0
            if price <= 0:
                continue
            photos    = item.get("photos", [])
            image_url = photos[0].get("url", "") if photos else ""
            results.append({
                "title":       item.get("title", ""),
                "price":       price,
                "url":         f"https://www.vinted.fr/items/{item['id']}",
                "image_url":   image_url,
                "brand":       item.get("brand_title", brand),
                "size":        item.get("size_title", ""),
                "description": item.get("description", ""),
                "platform":    "Vinted",
            })
    except Exception as e:
        log.error(f"Vinted scraper error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  VESTIAIRE COLLECTIVE
# ─────────────────────────────────────────────────────────────────

def scrape_vestiaire(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        # API de recherche Vestiaire
        url = "https://search.vestiairecollective.com/v1/product/search"
        payload = {
            "query": brand,
            "filters": {"price": {"max": max_price}},
            "pagination": {"limit": 20, "page": 1},
            "sort": "new",
            "country": "FR",
            "currency": "EUR",
        }
        headers = {
            **HEADERS_BASE,
            "Content-Type": "application/json",
            "Referer": "https://www.vestiairecollective.com/",
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("items", [])[:20]:
                price = item.get("price", {}).get("cents", 0) / 100
                if price <= 0:
                    continue
                link = item.get("link", "")
                full_url = f"https://www.vestiairecollective.com{link}" if link.startswith("/") else link
                results.append({
                    "title":       item.get("name", ""),
                    "price":       price,
                    "url":         full_url,
                    "image_url":   item.get("pictures", [{}])[0].get("src", "") if item.get("pictures") else "",
                    "brand":       item.get("brand", {}).get("name", brand),
                    "size":        item.get("size", {}).get("name", "") if isinstance(item.get("size"), dict) else "",
                    "description": item.get("name", ""),
                    "platform":    "Vestiaire Collective",
                })
        else:
            # Fallback scraping HTML
            html_url = f"https://www.vestiairecollective.com/search/?q={brand}&priceMax={max_price}&order=new"
            r2 = requests.get(html_url, headers=HEADERS_BASE, timeout=15)
            soup = BeautifulSoup(r2.text, "html.parser")
            for card in soup.select("article")[:20]:
                title_el = card.select_one("h2, [class*='title'], [class*='name']")
                price_el = card.select_one("[class*='price']")
                link_el  = card.select_one("a[href]")
                img_el   = card.select_one("img")
                if not title_el or not price_el or not link_el:
                    continue
                price = _parse_price(price_el.text)
                if not price:
                    continue
                href = link_el["href"]
                full_url = href if href.startswith("http") else f"https://www.vestiairecollective.com{href}"
                results.append({
                    "title":       title_el.text.strip(),
                    "price":       price,
                    "url":         full_url,
                    "image_url":   img_el.get("src", "") if img_el else "",
                    "brand":       brand,
                    "size":        "",
                    "description": title_el.text.strip(),
                    "platform":    "Vestiaire Collective",
                })
    except Exception as e:
        log.error(f"Vestiaire scraper error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  EBAY FRANCE
# ─────────────────────────────────────────────────────────────────

def scrape_ebay(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = "https://www.ebay.fr/sch/i.html"
        params = {
            "_nkw":   f"{brand} costume OR veste OR manteau OR blazer",
            "_sacat": "0",
            "_udhi":  max_price,
            "_sop":   "10",
            "LH_ItemCondition": "1000|1500|2000|2500",
        }
        resp = requests.get(url, params=params, headers=HEADERS_BASE, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for item in soup.select(".s-item")[:20]:
            title_el = item.select_one(".s-item__title")
            price_el = item.select_one(".s-item__price")
            link_el  = item.select_one("a.s-item__link")
            img_el   = item.select_one("img.s-item__image-img")
            if not title_el or not price_el or not link_el:
                continue
            if "Shop on eBay" in title_el.text:
                continue
            price = _parse_price(price_el.text)
            if not price:
                continue
            image_url = img_el.get("src") or img_el.get("data-src", "") if img_el else ""
            results.append({
                "title":       title_el.text.strip(),
                "price":       price,
                "url":         link_el["href"],
                "image_url":   image_url,
                "brand":       brand,
                "size":        "",
                "description": title_el.text.strip(),
                "platform":    "eBay",
            })
    except Exception as e:
        log.error(f"eBay scraper error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  LEBONCOIN
# ─────────────────────────────────────────────────────────────────

def scrape_leboncoin(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = "https://www.leboncoin.fr/recherche"
        params = {
            "text":      brand,
            "category":  "2",
            "price":     f"0-{max_price}",
            "shippable": "1",
        }
        headers = {**HEADERS_BASE, "Accept": "text/html,application/xhtml+xml,*/*"}
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        for card in soup.select("a[data-test-id='ad']")[:20]:
            title_el = card.select_one("[data-test-id='ad-title']")
            price_el = card.select_one("[data-test-id='price']")
            img_el   = card.select_one("img")
            if not title_el or not price_el:
                continue
            price = _parse_price(price_el.text)
            if not price:
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
        log.error(f"Leboncoin scraper error ({brand}): {e}")
    _sleep()
    return results


# ─────────────────────────────────────────────────────────────────
#  DISPATCHER GLOBAL
# ─────────────────────────────────────────────────────────────────

def scrape_all(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    results += scrape_vinted(brand, max_price)
    results += scrape_vestiaire(brand, max_price)
    results += scrape_ebay(brand, max_price)
    results += scrape_leboncoin(brand, max_price)
    return results

