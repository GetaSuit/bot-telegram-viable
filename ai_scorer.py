import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def is_worth_buying(title: str, brand: str, price: float, source: str) -> dict:
    """
    Question simple : vaut-il la peine d'acheter cet article pour le revendre ?
    Retourne keep=True par défaut si l'IA est indisponible.
    """
    if not ANTHROPIC_API_KEY:
        return _default()

    prompt = (
        f"Expert en revente luxe. Article sur {source} :\n"
        f"Marque: {brand} | Titre: {title} | Prix: {price}€\n\n"
        f"Est-ce qu'acheter cet article à {price}€ permet de le revendre avec profit ?\n"
        f"Réponds en JSON uniquement:\n"
        f'{{"keep":true/false,"reason":"1 phrase","market_value":euros_ou_null,"verdict":"excellent/bon/correct/faible/suspect"}}'
    )

    try:
        r = requests.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if r.status_code != 200:
            logger.warning(f"[AI] HTTP {r.status_code}")
            return _default()

        text = r.json()["content"][0]["text"].strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        logger.info(f"[AI] {brand} — keep={result.get('keep')} | {result.get('reason','')[:50]}")
        return result

    except Exception as e:
        logger.warning(f"[AI] Erreur: {e}")
        return _default()


def _default() -> dict:
    return {
        "keep": True,
        "reason": "",
        "market_value": None,
        "verdict": "correct",
    }
