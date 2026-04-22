import os
import json
import logging
import base64
import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

if ANTHROPIC_API_KEY:
    logger.info(f"[AI] Clé API chargée ({len(ANTHROPIC_API_KEY)} caractères)")
else:
    logger.error("[AI] ANTHROPIC_API_KEY manquante")


def fetch_image_base64(image_url: str) -> str | None:
    try:
        r = requests.get(image_url, timeout=10)
        r.raise_for_status()
        return base64.standard_b64encode(r.content).decode("utf-8")
    except Exception as e:
        logger.warning(f"[AI] Image non récupérable: {e}")
        return None


def analyze_article(
    title: str,
    brand: str,
    price: float,
    source: str,
    image_url: str = None,
) -> dict:
    if not ANTHROPIC_API_KEY:
        return _default_response()

    prompt = f"""Tu es un expert en mode luxe et sourcing de seconde main.

Article sur {source} :
- Marque : {brand}
- Titre : {title}
- Prix : {price}€

RÈGLE PRINCIPALE : keep doit être TRUE par défaut.
Mets keep à FALSE UNIQUEMENT si l'article est :
- Une contrefaçon évidente (fake, replica, inspired)
- Un parfum ou produit beauté
- Un article technologique (téléphone, ordi)
- Totalement hors-sujet (voiture, jouet, livre)

Pour TOUT le reste (vêtements, accessoires, sacs, même si pas parfait) → keep = TRUE

Analyse aussi :
- Est-ce une pièce de défilé ou collection connue ?
- Quelle est la valeur marché estimée ?

Réponds UNIQUEMENT en JSON :
{{
  "keep": <true SAUF si contrefaçon/parfum/tech/hors-sujet>,
  "is_trending": <true si tendance 2024-2026>,
  "is_authentic": <true si pas de doute évident>,
  "is_runway": <true si photo ou pièce de défilé>,
  "collection": <"Marque Saison Année" ex "Dior SS24" ou null>,
  "verdict": <"excellent" | "bon" | "correct" | "faible">,
  "reason": <une phrase courte>,
  "market_value": <valeur revente estimée en euros ou null>
}}"""

    content = []

    if image_url:
        img_b64 = fetch_image_base64(image_url)
        if img_b64:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": img_b64,
                },
            })

    content.append({"type": "text", "text": prompt})

    try:
        response = requests.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 400,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(f"[AI] HTTP {response.status_code}: {response.text[:200]}")
            return _default_response()

        text = response.json()["content"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        logger.info(
            f"[AI] {brand} — keep={result.get('keep')} | "
            f"{result.get('verdict')} | "
            f"runway={result.get('is_runway')} | "
            f"collection={result.get('collection')} | "
            f"{result.get('reason', '')[:50]}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[AI] JSON invalide: {e}")
        return _default_response()
    except Exception as e:
        logger.error(f"[AI] Erreur: {e}")
        return _default_response()


def _default_response() -> dict:
    """Par défaut on garde l'article si l'IA est indisponible."""
    return {
        "keep": True,
        "is_trending": False,
        "is_authentic": True,
        "is_runway": False,
        "collection": None,
        "verdict": "correct",
        "reason": "",
        "market_value": None,
    }
