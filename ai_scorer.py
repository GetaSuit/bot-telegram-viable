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


def analyze_article(title: str, brand: str, price: float, source: str) -> dict:
    """
    Envoie l'article à Claude pour analyse.
    Retourne un dict avec :
    - ai_score (0-100)
    - is_trending (bool)
    - is_authentic (bool)
    - verdict (str)
    - reason (str)
    """
    if not ANTHROPIC_API_KEY:
        return _default_response()

    prompt = f"""Tu es un expert en mode luxe et en sourcing de pièces de seconde main.
Analyse cet article mis en vente :

Marque : {brand}
Titre : {title}
Prix : {price}€
Source : {source}

Réponds UNIQUEMENT en JSON avec exactement ces champs :
{{
  "ai_score": <entier 0-100, pertinence et potentiel de revente>,
  "is_trending": <true/false, est-ce que cette pièce est tendance en 2025/2026>,
  "is_authentic": <true/false, le titre semble-t-il authentique ou suspect>,
  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,
  "reason": <une phrase courte expliquant ton verdict>
}}

Critères pour ai_score élevé :
- Pièce iconique ou très demandée de la marque
- Prix d'achat permettant une belle marge (revente ×2 minimum)
- Catégorie tendance (veste, manteau, sac)
- Titre clair et crédible
- Marque au goût du jour ou intemporelle

Critères pour is_trending :
- Marque portée par des célébrités récemment
- Pièce vue dans les défilés 2024/2025
- Style correspondant aux tendances actuelles (quiet luxury, tailoring, etc.)

Réponds uniquement avec le JSON, sans texte autour."""

    try:
        response = requests.post(
            ANTHROPIC_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        response.raise_for_status()
        content = response.json()["content"][0]["text"].strip()

        # Nettoyage si backticks
        content = content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)

        logger.info(f"[AI] {brand} — {result.get('verdict')} (score {result.get('ai_score')})")
        return result

    except Exception as e:
        logger.warning(f"[AI] Erreur analyse '{title}': {e}")
        return _default_response()


def _default_response() -> dict:
    """Réponse par défaut si l'API est indisponible."""
    return {
        "ai_score": 50,
        "is_trending": False,
        "is_authentic": True,
        "verdict": "correct",
        "reason": "Analyse IA indisponible",
    }
