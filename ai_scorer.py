import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

if ANTHROPIC_API_KEY:
    logger.info(f"[AI] Clé API chargée ({len(ANTHROPIC_API_KEY)} caractères)")
else:
    logger.error("[AI] ANTHROPIC_API_KEY manquante")


def analyze_article(title: str, brand: str, price: float, source: str) -> dict:
    if not ANTHROPIC_API_KEY:
        return _default_response()

    prompt = f"""Tu es un expert en mode luxe et sourcing de seconde main.

Article trouvé sur {source} :
- Marque : {brand}
- Titre : {title}
- Prix : {price}€

Décide si cet article vaut la peine d'être acheté pour revente.

Sois GÉNÉREUX dans ta sélection — garde tout ce qui pourrait intéresser un revendeur de luxe :
- Vestes, blazers, costumes, manteaux, sacs, pochettes
- Pièces de marque authentiques à bon prix
- Articles avec potentiel de revente ×1.5 minimum

Rejette UNIQUEMENT :
- Les contrefaçons évidentes
- Les articles clairement hors-sujet (parfums, chaussures, accessoires, tech)
- Les articles dont le prix est trop élevé pour dégager une marge

Réponds UNIQUEMENT en JSON valide :
{{
  "keep": <true ou false>,
  "is_trending": <true ou false>,
  "is_authentic": <true ou false>,
  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,
  "reason": <une phrase courte>,
  "market_value": <valeur marché estimée en euros ou null>
}}"""

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
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )

        if response.status_code != 200:
            logger.error(f"[AI] HTTP {response.status_code}: {response.text[:200]}")
            return _default_response()

        content = response.json()["content"][0]["text"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        logger.info(
            f"[AI] {brand} — keep={result.get('keep')} | "
            f"{result.get('verdict')} | {result.get('reason', '')[:60]}"
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
        "verdict": "correct",
        "reason": "",
        "market_value": None,
    }
