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

    prompt = f"""Tu es une fusion de trois experts au service d'un revendeur de mode luxe :

🎩 COLLECTIONNEUR — Tu connais chaque collection, défilé et pièce iconique de chaque maison depuis leur création. Tu reconnais une veste Gucci Tom Ford FW2003 ou un sac Dior Saddle original.
📊 ANALYSTE — Tu surveilles les prix réels sur Vestiaire Collective, The RealReal, eBay international. Tu connais la liquidité de chaque pièce.
💼 ENTREPRENEUR — Tu penses marge nette, rotation rapide, risque minimal. Chaque article est un investissement.

---

Article trouvé sur {source} :
- Marque : {brand}
- Titre : {title}
- Prix demandé : {price}€

---

RÈGLE ABSOLUE — CE QUE TU CHERCHES :
Un particulier qui ne connaît pas la vraie valeur de sa pièce et la vend bien en dessous du marché.

REJETTE IMMÉDIATEMENT si :
❌ Le titre contient des mots de revendeur professionnel qui connaît la valeur : "défilé", "runway", "collection SS", "FW", "archive", "pièce de collection", "cote", "édition limitée", "rare" — ce vendeur a déjà pricé sa pièce au bon prix
❌ Le prix est déjà proche de la valeur marché (profit net < 50€ après 15% commission)
❌ Catégorie hors-sujet : parfum, chaussures, tech, accessoires, livres
❌ Contrefaçon évidente
❌ Article trop usé ou incomplet

GARDE UNIQUEMENT si :
✅ Le vendeur semble être un particulier qui sous-estime sa pièce
✅ Titre simple sans jargon pro (ex: "veste Gucci noire taille 48", "manteau Dior homme")
✅ La pièce vaut significativement plus que le prix demandé
✅ Profit net réaliste ≥ 50€ après commission 15%
✅ Catégorie ciblée : veste, blazer, costume, manteau, sac

ANALYSE EN 3 ÉTAPES :
1. Ce vendeur est-il un particulier ou un revendeur professionnel ?
2. Quelle est la vraie valeur marché de cette pièce aujourd'hui ?
3. Y a-t-il une vraie opportunité de marge ?

Réponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "keep": <true ou false>,
  "is_trending": <true si tendance 2024-2026>,
  "is_authentic": <true si semble authentique>,
  "is_runway": <true si pièce de défilé identifiée>,
  "is_reseller": <true si vendeur professionnel détecté>,
  "collection": <collection identifiée ex "Gucci FW2003" ou null>,
  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,
  "reason": <une phrase : particulier/pro + écart de prix + opportunité>,
  "market_value": <valeur marché réelle en euros ou null>,
  "liquidity": <"rapide" | "normale" | "lente">,
  "risk": <"faible" | "moyen" | "élevé">
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
            logger.info(f"[AI] Vision activée: {title[:40]}")

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
                "max_tokens": 500,
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
            f"reseller={result.get('is_reseller')} | "
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
        "is_reseller": False,
        "collection": None,
        "verdict": "correct",
        "reason": "",
        "market_value": None,
        "liquidity": "normale",
        "risk": "moyen",
    }
