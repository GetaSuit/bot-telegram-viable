"""
scrapers.py — Vestiaire Collective uniquement
En attente API eBay officielle
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Connection": "keep-alive",
}

def _sleep():
    time.sleep(random.uniform(1.5, 2.5))

def _parse_price(text: str) -> float | None:
    cleaned = re.sub(r"[^\d.,]", "", str(text)).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def scrape_vestiaire(brand: str, max_price: int = 2000) -> list[dict]:
    results = []
    try:
        url = f"https://www.vestiairecollective.com/search/?q={requests.utils.quote(brand)}&order=new&priceMax={max_price}&currency=EUR"
        resp = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Méthode 1 : JSON embarqué dans la page
        for script in soup.find_all("script"):
            txt = script.string or ""
            if "catalogItems" in txt or "productList" in txt or '"price"' in txt:
                try:
                    # Cherche un tableau JSON d'articles
                    match = re.search(r'"items"\s*:\s*(\[.*?\])', txt, re.DOTALL)
                    if not match:
                        match = re.search(r'"products"\s*:\s*(\[.*?\])', txt, re.DOTALL)
                    if match:
                        items = json.loads(match.group(1))
                        for item in items[:20]:
                            price = float(item.get("price", {}).get("cents", 0)) / 100 if isinstance(item.get("price"), dict) else float(item.get("price", 0) or 0)
                            if not price or price > max_price:
                                continue
                            link = item.get("link", item.get("url", ""))
                            full_url = f"https://www.vestiairecollective.com{link}" if link.startswith("/") else link
                            pics = item.get("pictures", item.get("images", []))
                            image_url = pics[0].get("src", "") if pics and isinstance(pics[0], dict) else (pics[0] if pics else "")
                            results.append({
                                "title":       item.get("name", item.get("title", brand)),
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

        # Méthode 2 : HTML classique
        if not results:
            for card in soup.select("article, [class*='product'], [class*='Product']")[:25]:
                link_el  = card.select_one("a[href*='vestiairecollective']") or card.select_one("a[href]")
                price_el = card.select_one("[class*='price'], [class*='Price']")
                title_el = card.select_one("[class*='name'], [class*='title'], h2, h3, p")
                img_el   = card.select_one("img")

                if not link_el or not price_el:
                    continue
                price = _parse_price(price_el.text)
                if not price or price > max_price:
                    continue
                href = link_el.get("href", "")
                full_url = href if href.startswith("http") else f"https://www.vestiairecollective.com{href}"
                title = title_el.text.strip() if title_el else brand
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

        log.info(f"Vestiaire '{brand}': {len(results)} articles trouvés")

    except Exception as e:
        log.error(f"Vestiaire error ({brand}): {e}")

    _sleep()
    return results


def scrape_all(brand: str, max_price: int = 2000) -> list[dict]:
    return scrape_vestiaire(brand, max_price)
