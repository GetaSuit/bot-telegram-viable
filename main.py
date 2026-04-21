"""
main.py — Bot Telegram sourcing luxe @BigbigMoneyluxbot
python-telegram-bot 20.6 | Render.com
"""

import logging
import asyncio
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from config import (
    TELEGRAM_TOKEN,
    CHAT_ID,
    BRANDS,
    MIN_PRICE,
    MAX_PRICE,
    SCAN_INTERVAL_MINUTES,
)
from scrapers import search_ebay, search_vinted, search_all_sources
from database import init_db, is_already_seen, mark_as_seen

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
    logger.info("🌐 Serveur HTTP démarré sur port 10000")
    server.serve_forever()


# ──────────────────────────────────────────
# FORMATAGE ARTICLE
# ──────────────────────────────────────────

def format_article(item: dict, brand: str) -> str:
    title = item.get("title", "Sans titre")
    price = item.get("price", "?")
    source = item.get("source", "?")
    url = item.get("url", "")
    is_hype = item.get("is_hype", False)
    ai_verdict = item.get("ai_verdict", "")
    ai_reason = item.get("ai_reason", "")
    market_value = item.get("market_value")

    header = "🔥 *COUP DU JOUR* — Tendance du moment !\n\n" if is_hype else ""

    verdict_icons = {
        "excellent": "🏆",
        "bon": "✅",
        "correct": "👍",
        "faible": "💤",
        "suspect": "⚠️",
    }
    icon = verdict_icons.get(ai_verdict, "🔍")
    verdict_line = f"{icon} _{ai_reason}_\n\n" if ai_reason else ""

    market_line = ""
    if market_value:
        try:
            mv = float(market_value)
            px = float(str(price))
            profit = mv - px
            market_line = (
                f"💹 *Valeur marché estimée* : ~{mv:.0f}€\n"
                f"📊 *Profit potentiel* : +{profit:.0f}€\n"
            )
        except Exception:
            market_line = f"💹 *Valeur marché* : ~{market_value}€\n"

    return (
        f"{header}"
        f"{verdict_line}"
        f"🏷️ *{title}*\n\n"
        f"💰 *Prix demandé* : {price}€\n"
        f"{market_line}"
        f"📦 *Source* : {source}\n\n"
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

    if item.get("is_hype"):
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=(
                    f"🔥🔥 *COUP DU JOUR* 🔥🔥\n"
                    f"*{brand}* — Article tendance repéré !"
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

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
        logger.warning(f"[send_article] Photo échouée: {e}")
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
BATCH_SIZE = 3
MAX_PER_BRAND = 5

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
        "👑 *Bienvenue sur GetaSuit Sourcing*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 Ton assistant IA de sourcing luxe\n"
        "Chaque article est analysé par Claude :\n"
        "cote réelle · tendances · profit potentiel\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📦 *Sources* : eBay · Vinted\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Marques* : {len(BRANDS)} maisons surveillées\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Utilise le menu / pour accéder aux commandes"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Lancer un scan", callback_data="do_scan"),
            InlineKeyboardButton("🏷️ Voir les marques", callback_data="do_marques"),
        ],
        [
            InlineKeyboardButton("📊 Statut", callback_data="do_status"),
            InlineKeyboardButton("❓ Aide", callback_data="do_help"),
        ],
    ])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *Aide — GetaSuit Sourcing*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔄 /scan — Lance un scan immédiat\n"
        "🔎 /chercher — Recherche par marque\n"
        "   _Ex : /chercher Hermès_\n\n"
        "🏷️ /marques — Liste des maisons surveillées\n"
        "📊 /status — État du bot en temps réel\n"
        "🔬 /test\\_sources — Diagnostic eBay & Vinted\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *Comment fonctionne l'IA ?*\n\n"
        "Chaque article trouvé est analysé par Claude :\n"
        "• Cote réelle sur Vestiaire, RealReal, eBay\n"
        "• Archives de collections & défilés\n"
        "• Tendances actuelles (quiet luxury, tailoring)\n"
        "• Valeur marché estimée & profit potentiel\n\n"
        "🔥 *COUP DU JOUR* = pièce tendance repérée\n"
        "chez une star, en défilé ou en magazine"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    progress = _scan_cursor["index"]
    pct = int((progress / len(BRANDS)) * 100)
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    text = (
        "📊 *Statut — GetaSuit Sourcing*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 *Bot actif*\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
        f"🔁 *Scan auto* : toutes les {SCAN_INTERVAL_MINUTES} min\n"
        f"📦 *Progression* : [{bar}] {pct}%\n"
        f"   Marque {progress}/{len(BRANDS)} en cours\n\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Marques* : {len(BRANDS)} surveillées\n"
        f"🤖 *IA* : Claude Sonnet — actif\n"
        f"📡 *Sources* : eBay · Vinted"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorted_brands = sorted(BRANDS)
    # Affichage en 2 colonnes
    lines = ["🏷️ *Maisons surveillées*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for b in sorted_brands:
        lines.append(f"  · {b}")
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"*{len(BRANDS)} maisons au total*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 *Scan lancé*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 L'IA analyse chaque article...\n"
        "_Les résultats arrivent dans quelques instants_",
        parse_mode="Markdown"
    )
    context.application.job_queue.run_once(scan_job, when=0, name="scan_manuel")

async def cmd_chercher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🔎 *Recherche par marque*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "❌ Aucune marque précisée.\n\n"
            "*Utilisation :*\n"
            "`/chercher Hermès`\n"
            "`/chercher Tom Ford`\n\n"
            "Tape /marques pour voir la liste complète",
            parse_mode="Markdown"
        )
        return

    brand = " ".join(context.args)
    brand_match = next(
        (b for b in BRANDS if b.lower() == brand.lower()), None
    )

    if not brand_match:
        await update.message.reply_text(
            f"❌ *Marque non reconnue* : `{brand}`\n\n"
            f"Tape /marques pour voir la liste complète.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🔎 *Recherche en cours*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏷️ Marque : *{brand_match}*\n"
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🤖 Analyse IA de chaque article...\n\n"
        f"_Résultats dans quelques instants_",
        parse_mode="Markdown"
    )

    results = search_all_sources(brand_match)
    new_items = [r for r in results if not is_already_seen(r.get("url", ""))]

    if not new_items:
        await update.message.reply_text(
            f"⚠️ *Aucun résultat*\n\n"
            f"L'IA n'a retenu aucun article pour *{brand_match}*.\n"
            f"Réessaie plus tard ou scanne une autre marque.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"✅ *{len(new_items)} article(s) sélectionné(s)* par l'IA pour *{brand_match}*",
        parse_mode="Markdown"
    )

    for item in new_items[:15]:
        url = item.get("url", "")
        if url:
            mark_as_seen(url)
        await send_article(context.bot, item, brand_match)
        await asyncio.sleep(1.5)

async def cmd_test_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔬 *Diagnostic des sources*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "_Test en cours..._",
        parse_mode="Markdown"
    )
    brand = "Hermès"
    lines = [
        f"🔬 *Diagnostic — {brand}*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n",
    ]
    for name, fn in [("eBay", search_ebay), ("Vinted", search_vinted)]:
        try:
            res = fn(brand)
            if res:
                sample = res[0]
                lines.append(
                    f"✅ *{name}* : {len(res)} article(s) validé(s)\n"
                    f"   📌 {str(sample.get('title',''))[:45]}…\n"
                    f"   💰 {sample.get('price')}€\n"
                    f"   🤖 _{sample.get('ai_reason', 'Analyse IA')[:60]}_"
                )
            else:
                lines.append(f"⚠️ *{name}* : aucun article retenu par l'IA")
        except Exception as e:
            lines.append(f"❌ *{name}* : erreur\n   `{str(e)[:60]}`")
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS BOUTONS INLINE
# ──────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "interested":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Sauvegardé", callback_data="noop")
            ]])
        )
    elif query.data == "ignore":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑️ Ignoré", callback_data="noop")
            ]])
        )
    elif query.data == "do_scan":
        await query.message.reply_text(
            "🔄 *Scan lancé en arrière-plan...*",
            parse_mode="Markdown"
        )
        context.application.job_queue.run_once(scan_job, when=0, name="scan_btn")
    elif query.data == "do_marques":
        sorted_brands = sorted(BRANDS)
        lines = ["🏷️ *Maisons surveillées*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for b in sorted_brands:
            lines.append(f"  · {b}")
        lines.append(f"\n*{len(BRANDS)} maisons au total*")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
    elif query.data == "do_status":
        progress = _scan_cursor["index"]
        pct = int((progress / len(BRANDS)) * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        await query.message.reply_text(
            f"📊 *Statut*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 Bot actif\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n"
            f"📦 Progression : [{bar}] {pct}%\n"
            f"🤖 IA Claude : active",
            parse_mode="Markdown"
        )
    elif query.data == "do_help":
        await query.message.reply_text(
            "❓ *Commandes disponibles*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔄 /scan — Scan immédiat\n"
            "🔎 /chercher — Recherche par marque\n"
            "🏷️ /marques — Liste des maisons\n"
            "📊 /status — État du bot\n"
            "🔬 /test\\_sources — Diagnostic\n"
            "❓ /help — Aide complète",
            parse_mode="Markdown"
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

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("marques", cmd_marques))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("chercher", cmd_chercher))
    app.add_handler(CommandHandler("test_sources", cmd_test_sources))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Scan automatique
    app.job_queue.run_repeating(
        scan_job,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=60,
        name="scan_auto",
    )

    logger.info(
        f"🚀 Bot démarré — {len(BRANDS)} marques | "
        f"IA Claude | {SCAN_INTERVAL_MINUTES}min"
    )

    while True:
        try:
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
        except Exception as e:
            logger.warning(f"⚠️ Conflit, redémarrage dans 15s : {e}")
            time.sleep(15)
            continue
        break


if __name__ == "__main__":
    main()
