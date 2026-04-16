"""
main.py — Bot Telegram sourcing luxe @BigbigMoneyluxbot
python-telegram-bot 20.6 | Render.com
"""

import logging
import asyncio
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

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
from scrapers import search_ebay, search_vinted, search_all_sources
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
# SERVEUR HTTP — KEEP ALIVE RENDER
# ──────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass

def start_health_server():
    server = HTTPServer(("0.0.0.0", 10000), HealthHandler)
    logger.info("🌐 Serveur HTTP keep-alive démarré sur port 10000")
    server.serve_forever()


# ──────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────

MULTIPLIERS = {"T1": 2.5, "T2": 2.0, "T3": 1.8}

def get_tier(brand: str) -> str:
    if brand in TIER1_BRANDS:
        return "T1"
    if brand in TIER2_BRANDS:
        return "T2"
    return "T3"

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
        return "💰 Prix non disponible"

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

def build_keyboard(item: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Voir l'annonce", url=item.get("url", ""))],
        [
            InlineKeyboardButton("✅ Intéressant", callback_data="interested"),
            InlineKeyboardButton("❌ Ignorer", callback_data="ignore"),
        ],
    ])


# ──────────────────────────────────────────
# ENVOI ARTICLE
# ──────────────────────────────────────────

async def send_article(bot, item: dict, brand: str):
    text = format_article(item, brand)
    keyboard = build_keyboard(item)
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
            )
    except Exception as e:
        logger.warning(f"[send_article] Photo échouée, fallback texte: {e}")
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
# SCAN PAR BATCH
# ──────────────────────────────────────────

_scan_cursor = {"index": 0}
BATCH_SIZE = 2
MAX_PER_BRAND = 1

async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    start = _scan_cursor["index"]
    batch = BRANDS[start: start + BATCH_SIZE]
    _scan_cursor["index"] = (start + BATCH_SIZE) % len(BRANDS)

    logger.info(f"🔄 Scan batch [{start}→{start + BATCH_SIZE}] : {batch}")
    total_sent = 0

    for brand in batch:
        try:
            results = search_all_sources(brand)
            new_items = [r for r in results if not is_already_seen(r.get("url", ""))]
            for item in new_items[:MAX_PER_BRAND]:
                url = item.get("url", "")
                if url:
                    mark_as_seen(url)
                await send_article(context.bot, item, brand)
                total_sent += 1
                await asyncio.sleep(3)
        except Exception as e:
            logger.error(f"[scan_job] Erreur '{brand}': {e}")
        await asyncio.sleep(5)

    logger.info(f"✅ Batch terminé — {total_sent} articles envoyés")


# ──────────────────────────────────────────
# COMMANDES
# ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Bot Sourcing Luxe actif*\n\n"
        "📦 Sources : eBay · Vinted\n"
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ {len(BRANDS)} marques surveillées\n\n"
        "Commandes :\n"
        "/scan — Scan automatique\n"
        "/chercher — Rechercher une marque\n"
        "/test\\_sources — Tester les sources\n"
        "/marques — Marques par tier\n"
        "/status — État du bot\n"
        "/help — Aide"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Aide — Bot Sourcing Luxe*\n\n"
        "/start — Démarrer\n"
        "/scan — Scan manuel\n"
        "/chercher <marque> — Ex: `/chercher Hermès`\n"
        "/test\\_sources — Diagnostic sources\n"
        "/marques — Liste des marques\n"
        "/status — État\n"
        "/help — Ce message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    progress = _scan_cursor["index"]
    text = (
        "📊 *Statut du bot*\n\n"
        f"✅ Heure : {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"🔁 Scan auto toutes les : {SCAN_INTERVAL_MINUTES} min\n"
        f"📦 Batch en cours : marque {progress}/{len(BRANDS)}\n"
        f"💶 Fourchette : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ Marques surveillées : {len(BRANDS)}\n"
        f"📡 Sources : eBay · Vinted"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text("🔄 Scan lancé en arrière-plan...")
    context.application.job_queue.run_once(scan_job, when=0, name="scan_manuel")

async def cmd_chercher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "❌ Précise une marque.\nEx: `/chercher Hermès`",
            parse_mode="Markdown"
        )
        return

    brand = " ".join(context.args)
    brand_match = next(
        (b for b in BRANDS if b.lower() == brand.lower()), None
    )

    if not brand_match:
        await update.message.reply_text(
            f"❌ Marque `{brand}` non reconnue.\nTape /marques pour voir la liste.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🔍 Recherche en cours pour *{brand_match}*...",
        parse_mode="Markdown"
    )

    results = search_all_sources(brand_match)
    new_items = [r for r in results if not is_already_seen(r.get("url", ""))]

    if not new_items:
        await update.message.reply_text(
            f"⚠️ Aucun nouvel article trouvé pour *{brand_match}*.",
            parse_mode="Markdown"
        )
        return

    for item in new_items[:5]:
        url = item.get("url", "")
        if url:
            mark_as_seen(url)
        await send_article(context.bot, item, brand_match)
        await asyncio.sleep(1.5)

async def cmd_test_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Test des sources en cours...")
    brand = "Hermès"
    lines = [f"📊 *Diagnostic* — `{brand}` ({MIN_PRICE}€–{MAX_PRICE}€)\n"]
    for name, fn in [("eBay", search_ebay), ("Vinted", search_vinted)]:
        try:
            res = fn(brand)
            if res:
                sample = res[0]
                lines.append(
                    f"✅ *{name}* : {len(res)} résultats\n"
                    f"   Ex: {str(sample.get('title',''))[:40]}… — {sample.get('price')}€"
                )
            else:
                lines.append(f"⚠️ *{name}* : 0 résultat")
        except Exception as e:
            lines.append(f"❌ *{name}* : `{str(e)[:80]}`")
    lines.append(f"\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS BOUTONS
# ──────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "interested":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Marqué comme intéressant", callback_data="noop")
            ]])
        )
    elif query.data == "ignore":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑️ Ignoré", callback_data="noop")
            ]])
        )


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

def main():
    thread = threading.Thread(target=start_health_server, daemon=True)
    thread.start()

    init_db()
    logger.info("🗄️ DB initialisée")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("marques", cmd_marques))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("chercher", cmd_chercher))
    app.add_handler(CommandHandler("test_sources", cmd_test_sources))
    app.add_handler(CallbackQueryHandler(button_callback))

    app.job_queue.run_repeating(
        scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=30,
        name="scan_auto",
    )

    logger.info(f"🚀 Bot démarré — {len(BRANDS)} marques | batch {BATCH_SIZE} | {SCAN_INTERVAL_MINUTES}min")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
