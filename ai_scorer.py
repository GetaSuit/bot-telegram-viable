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

    prompt = (
        f"Tu es un expert en revente de mode luxe.\n\n"
        f"Article trouvé sur {source} :\n"
        f"- Marque : {brand}\n"
        f"- Titre : {title}\n"
        f"- Prix demandé : {price}€\n\n"
        f"Question unique : Est-ce qu'acheter cet article à {price}€ "
        f"permet de le revendre avec un profit intéressant ?\n\n"
        f"Réponds UNIQUEMENT en JSON valide :\n"
        f"{{\n"
        f'  "keep": <true si profitable, false sinon>,\n'
        f'  "is_trending": <true si pièce tendance en 2025/2026>,\n'
        f'  "is_authentic": <true si semble authentique>,\n'
        f'  "is_runway": <true si pièce de défilé identifiable>,\n'
        f'  "collection": <collection identifiée ou null>,\n'
        f'  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,\n'
        f'  "reason": <une phrase courte sur la rentabilité>,\n'
        f'  "market_value": <prix de revente réaliste en euros ou null>,\n'
        f'  "liquidity": <"rapide" | "normale" | "lente">,\n'
        f'  "risk": <"faible" | "moyen" | "élevé">\n'
        f"}}"
    )

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
            f"market={result.get('market_value')}€ | "
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
    return {
        "keep": True,
        "is_trending": False,
        "is_authentic": True,
        "is_runway": False,
        "collection": None,
        "verdict": "correct",
        "reason": "",
        "market_value": None,
        "liquidity": "normale",
        "risk": "moyen",
    }
