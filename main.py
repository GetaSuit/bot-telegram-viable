"""
main.py — Bot Telegram de sourcing luxe @BigbigMoneyluxbot
Stack : python-telegram-bot 20.6 | eBay Browse API | Vinted API | Leboncoin API
Déployé sur Render.com (Web Service)
"""

import logging
import asyncio
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    JobQueue,
)

from config import (
    TELEGRAM_TOKEN,
    CHAT_ID,
    BRANDS,
    MIN_PRICE,
    MAX_PRICE,
    TIER1_BRANDS,
    TIER2_BRANDS,
    TIER3_BRANDS,
    SCAN_INTERVAL_MINUTES,
)
from scrapers import search_ebay, search_vinted, search_leboncoin, search_all_sources
from database import init_db, is_already_seen, mark_as_seen

# ──────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# HELPERS — CALCUL REVENTE & FORMATAGE
# ──────────────────────────────────────────

def get_tier(brand: str) -> str:
    if brand in TIER1_BRANDS:
        return "T1"
    if brand in TIER2_BRANDS:
        return "T2"
    return "T3"

MULTIPLIERS = {"T1": 2.5, "T2": 2.0, "T3": 1.8}

def estimate_resale(price_str: str, brand: str) -> str:
    try:
        price = float(str(price_str).replace(",", ".").replace("€", "").strip())
        tier = get_tier(brand)
        mult = MULTIPLIERS[tier]
        resale = price * mult
        profit = resale - price
        return (
            f"💰 Achat : {price:.0f}€\n"
            f"📈 Revente estimée ({tier} ×{mult}) : {resale:.0f}€\n"
            f"✅ Marge brute : +{profit:.0f}€"
        )
    except Exception:
        return "💰 Prix non calculable"

def format_article(item: dict, brand: str) -> str:
    title = item.get("title", "Sans titre")
    price = item.get("price", "?")
    source = item.get("source", "?")
    url = item.get("url", "")
    resale_info = estimate_resale(str(price), brand)
    return (
        f"🏷️ *{title}*\n"
        f"🔍 Source : {source}\n"
        f"{resale_info}\n"
        f"🔗 [Voir l'annonce]({url})"
    )

def build_article_keyboard(item: dict) -> InlineKeyboardMarkup:
    url = item.get("url", "")
    keyboard = [
        [InlineKeyboardButton("🔗 Voir l'annonce", url=url)],
        [
            InlineKeyboardButton("✅ Intéressant", callback_data="interested"),
            InlineKeyboardButton("❌ Ignorer", callback_data="ignore"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ──────────────────────────────────────────
# ENVOI D'UN ARTICLE AU CHAT
# ──────────────────────────────────────────

async def send_article(bot, item: dict, brand: str):
    """Envoie un article formaté dans le canal Telegram."""
    text = format_article(item, brand)
    keyboard = build_article_keyboard(item)
    image = item.get("image")

    try:
        if image:
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=image,
                caption=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
    except Exception as e:
        logger.warning(f"[send_article] Erreur envoi '{item.get('title')}': {e}")
        # Fallback sans image si l'envoi photo échoue
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as e2:
            logger.error(f"[send_article] Fallback échoué: {e2}")


# ──────────────────────────────────────────
# SCAN AUTOMATIQUE (JOB RÉCURRENT)
# ──────────────────────────────────────────

async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Scanne toutes les marques sur toutes les sources."""
    logger.info("🔄 Début du scan automatique...")
    total_sent = 0

    for brand in BRANDS:
        try:
            results = search_all_sources(brand)
            new_results = [r for r in results if not is_already_seen(r.get("url", ""))]

            for item in new_results:
                url = item.get("url", "")
                if url:
                    mark_as_seen(url)
                await send_article(context.bot, item, brand)
                total_sent += 1
                await asyncio.sleep(1.5)  # évite le flood Telegram

        except Exception as e:
            logger.error(f"[scan_job] Erreur marque '{brand}': {e}")
        
        await asyncio.sleep(2)  # délai entre marques

    logger.info(f"✅ Scan terminé — {total_sent} nouveaux articles envoyés")

    if total_sent == 0:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"🔄 Scan terminé à {datetime.now().strftime('%H:%M')} — Aucun nouvel article.",
        )


# ──────────────────────────────────────────
# COMMANDES BOT
# ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /start"""
    text = (
        "👋 *Bot Sourcing Luxe actif*\n\n"
        "📦 Sources : eBay · Vinted · Leboncoin\n"
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ {len(BRANDS)} marques surveillées\n\n"
        "Commandes disponibles :\n"
        "/scan — Lancer un scan maintenant\n"
        "/test\\_sources — Tester les 3 sources\n"
        "/marques — Voir les marques surveillées\n"
        "/status — État du bot\n"
        "/help — Aide"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /help"""
    text = (
        "📖 *Aide — Bot Sourcing Luxe*\n\n"
        "/start — Démarrer\n"
        "/scan — Scan manuel immédiat\n"
        "/test\\_sources — Diagnostic des 3 sources\n"
        "/marques — Liste des marques\n"
        "/status — Infos & état\n"
        "/help — Ce message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /status"""
    text = (
        "📊 *Statut du bot*\n\n"
        f"✅ Actif depuis : {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"🔁 Scan auto toutes les : {SCAN_INTERVAL_MINUTES} min\n"
        f"💶 Fourchette : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ Marques : {len(BRANDS)}\n"
        f"📦 Sources : eBay, Vinted, Leboncoin\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /marques — Liste les marques par tier"""
    t1 = "\n".join(f"  · {b}" for b in sorted(TIER1_BRANDS))
    t2 = "\n".join(f"  · {b}" for b in sorted(TIER2_BRANDS))
    t3 = "\n".join(f"  · {b}" for b in sorted(TIER3_BRANDS))
    text = (
        "🏷️ *Marques surveillées*\n\n"
        f"🥇 *Tier 1 — ×2.5* :\n{t1}\n\n"
        f"🥈 *Tier 2 — ×2.0* :\n{t2}\n\n"
        f"🥉 *Tier 3 — ×1.8* :\n{t3}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /scan — Scan manuel immédiat"""
    await update.message.reply_text("🔄 Scan en cours sur toutes les sources...")
    await scan_job(context)
    await update.message.reply_text("✅ Scan manuel terminé.")


async def cmd_test_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Commande /test_sources — Teste chaque source sur une marque pilote"""
    await update.message.reply_text("🔍 Test des sources en cours...")
    brand = "Hermès"
    lines = [f"📊 *Diagnostic sources* — `{brand}` ({MIN_PRICE}€–{MAX_PRICE}€)\n"]

    tests = [
        ("eBay", search_ebay),
        ("Vinted", search_vinted),
        ("Leboncoin", search_leboncoin),
    ]

    for name, fn in tests:
        try:
            results = fn(brand)
            if results:
                sample = results[0]
                lines.append(
                    f"✅ *{name}* : {len(results)} résultats\n"
                    f"   Ex: {sample.get('title', '')[:40]}… — {sample.get('price')}€"
                )
            else:
                lines.append(f"⚠️ *{name}* : 0 résultat (source vide ou bloquée)")
        except Exception as e:
            lines.append(f"❌ *{name}* : erreur — `{str(e)[:80]}`")

    lines.append(f"\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS BOUTONS INLINE
# ──────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "interested":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⭐ Marqué comme intéressant", callback_data="noop")]
            ])
        )
    elif query.data == "ignore":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Ignoré", callback_data="noop")]
            ])
        )


# ──────────────────────────────────────────
# POINT D'ENTRÉE PRINCIPAL
# ──────────────────────────────────────────

def main():
    # Initialisation de la base de données anti-doublons
    init_db()
    logger.info("🗄️ Base de données initialisée")

    # Construction de l'application Telegram
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    # ── Handlers commandes
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("marques", cmd_marques))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("test_sources", cmd_test_sources))

    # ── Handler boutons inline
    app.add_handler(CallbackQueryHandler(button_callback))

    # ── Job récurrent : scan automatique
    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(
        scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=30,  # premier scan 30s après démarrage
        name="scan_auto",
    )

    logger.info(
        f"🚀 Bot démarré — scan toutes les {SCAN_INTERVAL_MINUTES} min | "
        f"{len(BRANDS)} marques | {MIN_PRICE}€–{MAX_PRICE}€"
    )

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
