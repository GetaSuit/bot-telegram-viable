import os
import json
import logging
import requests

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def analyze(title: str, brand: str, price: float) -> dict:
    """
    Analyse complète de l'article :
    - Intérêt à la revente (×2 minimum)
    - Authenticité
    - Matière / qualité exceptionnelle
    - Pièce d'archive, rare ou de défilé
    - Vendeur particulier ou pro
    """
    if not ANTHROPIC_API_KEY:
        return _default()

    prompt = (
        f"Tu es un expert en mode luxe masculine et en revente.\n\n"
        f"Article eBay :\n"
        f"- Marque : {brand}\n"
        f"- Titre : {title}\n"
        f"- Prix : {price}€\n\n"
        f"Analyse cet article selon ces 5 critères :\n\n"
        f"1. RENTABILITÉ : Est-ce qu'on peut revendre cet article au moins 2× son prix d'achat ?\n"
        f"   Base-toi sur les prix réels actuels sur Vestiaire Collective et The RealReal.\n\n"
        f"2. AUTHENTICITÉ : Le titre semble-t-il authentique ? "
        f"Y a-t-il des signaux d'alerte (orthographe, description vague, prix trop bas) ?\n\n"
        f"3. MATIÈRE/QUALITÉ : S'agit-il d'une pièce exceptionnelle ? "
        f"(cachemire, laine vierge, soie, tissu japonais, fait main, etc.)\n\n"
        f"4. RARETÉ/ARCHIVE/DÉFILÉ : Cette pièce est-elle rare, d'archive ou de défilé ? "
        f"Remonte toutes les collections de {brand} pour identifier cette pièce.\n\n"
        f"5. TYPE DE VENDEUR : S'agit-il d'un particulier (titre simple, peu de stock) "
        f"ou d'un revendeur pro (plusieurs annonces similaires, prix au marché) ?\n\n"
        f"Réponds UNIQUEMENT en JSON valide :\n"
        f'{{"keep":true/false,"resale_value":euros,"reason":"1 phrase synthèse",'
        f'"is_authentic":true/false,"is_rare":false,"is_runway":false,'
        f'"material_quality":"normale/bonne/exceptionnelle","seller_type":"particulier/pro"}}'
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
                "max_tokens": 250,
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

        logger.info(
            f"[AI] {brand} | keep={result.get('keep')} | "
            f"revente={result.get('resale_value')}€ | "
            f"auth={result.get('is_authentic')} | "
            f"rare={result.get('is_rare')} | "
            f"vendeur={result.get('seller_type')} | "
            f"{result.get('reason','')[:50]}"
        )
        return result

    except Exception as e:
        logger.warning(f"[AI] Erreur: {e}")
        return _default()


def _default() -> dict:
    return {
        "keep": True,
        "resale_value": None,
        "reason": "",
        "is_authentic": True,
        "is_rare": False,
        "is_runway": False,
        "material_quality": "normale",
        "seller_type": "particulier",
    }
