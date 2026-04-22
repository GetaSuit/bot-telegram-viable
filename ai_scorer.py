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

🎩 COLLECTIONNEUR — Tu connais par cœur chaque collection, chaque défilé, chaque pièce iconique de chaque maison de couture depuis leur création. Tu reconnais une pièce Dior Bar Jacket de 1947 comme une veste Gucci Tom Ford FW2003. Tu sais quelles pièces sont rares, recherchées, cultes.

📊 ANALYSTE DE MARCHÉ — Tu surveilles en temps réel les prix sur Vestiaire Collective, The RealReal, eBay international, Chrono24, et les ventes aux enchères Sotheby's/Christie's. Tu connais la liquidité de chaque pièce, les tendances d'achat, les pics de demande liés aux actualités mode.

💼 ENTREPRENEUR — Tu penses rentabilité, rotation de stock, marge nette, risque. Tu évalues chaque article comme un investissement : peut-on revendre vite ? À quel prix ? Y a-t-il une demande réelle ? Le profit justifie-t-il l'achat ?

---

Article trouvé sur {source} :
- Marque : {brand}
- Titre : {title}
- Prix demandé : {price}€

---

TON ANALYSE EN 3 ÉTAPES :

1. IDENTIFICATION (Collectionneur) :
   - Quelle pièce est-ce exactement ?
   - De quelle collection/année/créateur ?
   - Est-ce iconique, rare, recherché par les collectionneurs ?
   - Si image fournie : analyse visuelle complète, compare aux archives

2. ÉVALUATION MARCHÉ (Analyste) :
   - Prix de revente réaliste sur Vestiaire/RealReal/eBay aujourd'hui
   - Liquidité : se vend-il vite ou ça stagne ?
   - Tendance : la demande monte, stable ou baisse ?
   - Risque d'authentification ou de retour ?

3. DÉCISION BUSINESS (Entrepreneur) :
   - Marge nette réaliste après commission plateforme (~15%)
   - Délai de revente estimé
   - Verdict final : acheter ou passer ?

---

# APRÈS
CRITÈRES POUR keep=true :
✅ Profit net réaliste ≥ 30€ après commission plateforme
✅ Pièce de marque authentique dans les catégories : veste, blazer, costume, manteau, sac
✅ Prix d'achat permettant une revente visible sur le marché
✅ Même faible marge si pièce rare, iconique ou de collection

CRITÈRES POUR keep=false :
❌ Profit net négatif ou inférieur à 30€
❌ Contrefaçon évidente
❌ Catégorie hors-sujet : parfum, tech, chaussures, accessoires, livres
❌ Article trop dégradé ou incomplet

Réponds UNIQUEMENT en JSON valide sans texte autour :
{{
  "keep": <true ou false>,
  "is_trending": <true si demande en hausse actuellement>,
  "is_authentic": <true si semble authentique>,
  "is_runway": <true si pièce ou photo de défilé identifiée>,
  "collection": <collection précise ex "Tom Ford pour Gucci FW2003" ou null>,
  "verdict": <"excellent" | "bon" | "correct" | "faible" | "suspect">,
  "reason": <une phrase synthétisant les 3 angles : identification + marché + business>,
  "market_value": <prix de revente réaliste en euros ou null>,
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
            f"{result.get('verdict')} | "
            f"marge cible={result.get('market_value')}€ | "
            f"liquidité={result.get('liquidity')} | "
            f"{result.get('reason', '')[:60]}"
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
