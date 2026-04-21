"""
ai_scorer.py — Claude décide seul si l'article vaut le coup
"""

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
    """
    Claude analyse l'article et décide s'il vaut la peine d'être envoyé.
    Il se base sur sa connaissance des cotes, archives, tendances et marché.
    Retourne : keep (bool), verdict, reason, is_trending.
    """
    if not ANTHROPIC_API_KEY:
        return _default_response()

    prompt = f"""Tu es un expert en mode luxe, en sourcing de seconde main et en revente.

Un article vient d'être trouvé sur {source} :
- Marque : {brand}
- Titre : {title}
- Prix demandé : {price}€

Ta mission : décider si cet article vaut la peine d'être acheté pour être revendu avec profit.

Pour cela, base-toi sur :
1. Ta connaissance de la cote réelle de cette pièce sur le marché (Vestiaire Collective, The RealReal, eBay, Vinted)
2. Les archives de défilés et collections de la marque
3. Les tendances actuelles (quiet luxury, tailoring, pièces iconiques)
4. La rareté et la demande de ce type de pièce
5. Si le prix demandé permet une marge intéressante à la revente

Réponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "keep": <true si l'article vaut le coup, false sinon>,
  "is_trending": <true si la pièce est tendance en ce moment>,
  "is_authentic": <true si le titre semble légitime>,
  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,
  "reason": <une phrase expliquant pourquoi garder ou ignorer cet article>,
  "market_value": <estimation de la valeur marché actuelle en euros, ou null si inconnu>
}}

Sois strict : ne garde que les vrais opportunités. Si tu n'as pas assez d'infos, mets keep à false."""

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
        "keep": True,  # si IA indispo, on laisse passer
        "is_trending": False,
        "is_authentic": True,
        "verdict": "correct",
        "reason": "",
        "market_value": None,
    }
