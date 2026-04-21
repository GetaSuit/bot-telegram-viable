"""
ai_scorer.py — Analyse IA des articles via Claude API
"""

import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Log au démarrage pour vérifier que la clé est bien chargée
if ANTHROPIC_API_KEY:
    logger.info(f"[AI] Clé API chargée ({len(ANTHROPIC_API_KEY)} caractères)")
else:
    logger.error("[AI] ⚠️ ANTHROPIC_API_KEY non définie — analyse IA désactivée")


def analyze_article(title: str, brand: str, price: float, source: str) -> dict:
    if not ANTHROPIC_API_KEY:
        logger.warning("[AI] Clé API manquante")
        return _default_response()

    prompt = f"""Tu es un expert en mode luxe et sourcing de seconde main.
Analyse cet article :

Marque : {brand}
Titre : {title}
Prix : {price}€
Source : {source}

Réponds UNIQUEMENT en JSON valide, sans texte autour :
{{
  "ai_score": <entier 0-100>,
  "is_trending": <true ou false>,
  "is_authentic": <true ou false>,
  "verdict": <"excellent" ou "bon" ou "correct" ou "faible" ou "suspect">,
  "reason": <une phrase courte>
}}

Critères ai_score élevé :
- Pièce iconique ou très recherchée
- Prix permettant revente ×2 minimum
- Catégorie : veste, manteau, sac
- Titre crédible et précis

Critères is_trending :
- Marque portée par des célébrités en 2025/2026
- Style quiet luxury, tailoring, pièces de défilé récent"""

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
            logger.error(f"[AI] Erreur HTTP {response.status_code}: {response.text[:200]}")
            return _default_response()

        content = response.json()["content"][0]["text"].strip()
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        logger.info(f"[AI] ✅ {brand} — {result.get('verdict')} (score {result.get('ai_score')})")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"[AI] JSON invalide: {e}")
        return _default_response()
    except Exception as e:
        logger.error(f"[AI] Erreur: {e}")
        return _default_response()


def _default_response() -> dict:
    return {
        "ai_score": 50,
        "is_trending": False,
        "is_authentic": True,
        "verdict": "correct",
        "reason": "Analyse IA indisponible",
    }
