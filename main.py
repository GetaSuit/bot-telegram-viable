²"""
main.py — Bot Telegram sourcing luxe @BigbigMoneyluxbot
python-telegram-bot 20.6 | Render.com
"""

import logging
import asyncio
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
from scrapers import search_vinted, search_all_sources
from database import init_db, is_already_seen, mark_as_seen

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_scan_cursor = {"index": 0}
BATCH_SIZE = 2
MAX_PER_BRAND = 5


# ──────────────────────────────────────────
# SERVEUR HTTP
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
    is_runway = item.get("is_runway", False)
    collection = item.get("collection")
    ai_verdict = item.get("ai_verdict", "")
    ai_reason = item.get("ai_reason", "")
    market_value = item.get("market_value")
    liquidity = item.get("liquidity", "")
    risk = item.get("risk", "")

    header = "🔥 *COUP DU JOUR* — Tendance du moment !\n\n" if is_hype else ""
    runway_line = "🎭 *Pièce de défilé identifiée*\n" if is_runway else ""
    collection_line = f"👗 *Collection* : {collection}\n" if collection else ""

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
            profit_brut = mv - px
            commission = mv * 0.15
            profit_net = profit_brut - commission
            market_line = (
                f"💹 *Revente estimée* : ~{mv:.0f}€\n"
                f"📊 *Profit net* (~15% comm.) : +{profit_net:.0f}€\n"
            )
        except Exception:
            market_line = f"💹 *Revente estimée* : ~{market_value}€\n"

    liquidity_icons = {"rapide": "🟢", "normale": "🟡", "lente": "🔴"}
    risk_icons = {"faible": "🟢", "moyen": "🟡", "élevé": "🔴"}
    meta_line = ""
    if liquidity or risk:
        l_icon = liquidity_icons.get(liquidity, "⚪")
        r_icon = risk_icons.get(risk, "⚪")
        meta_line = f"{l_icon} *Liquidité* : {liquidity} · {r_icon} *Risque* : {risk}\n"

    return (
        f"{header}"
        f"{runway_line}"
        f"{collection_line}"
        f"{verdict_line}"
        f"🏷️ *{title}*\n\n"
        f"💰 *Prix demandé* : {price}€\n"
        f"{market_line}"
        f"{meta_line}"
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

    if item.get("is_hype") or item.get("is_runway"):
        try:
            emoji = "🎭" if item.get("is_runway") else "🔥🔥"
            label = "PIÈCE DE DÉFILÉ" if item.get("is_runway") else "COUP DU JOUR"
            await bot.send_message(
                chat_id=CHAT_ID,
                text=f"{emoji} *{label}* {emoji}\n*{brand}* — Article exceptionnel repéré !",
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
        "cote réelle · collections · archives · profit\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
       f"📦 *Source* : Vinted\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Marques* : {len(BRANDS)} maisons surveillées\n"
        f"🔁 *Scan auto* : toutes les {SCAN_INTERVAL_MINUTES // 60}h\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Utilise le menu / pour accéder aux commandes"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Lancer un scan", callback_data="do_scan"),
            InlineKeyboardButton("🏷️ Les marques", callback_data="do_marques"),
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
        "🏷️ /marques — Maisons surveillées\n"
        "📊 /status — État du bot\n"
        "🔬 /test\\_sources — Diagnostic\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *Analyse IA par article :*\n\n"
        "• Détection particulier vs revendeur pro\n"
        "• Cote réelle (Vestiaire, RealReal, eBay)\n"
        "• Archives de toutes les collections\n"
        "• Détection pièces de défilé\n"
        "• Profit net estimé après commission\n"
        "• Liquidité & niveau de risque\n\n"
        "🎭 *PIÈCE DE DÉFILÉ* = collection identifiée\n"
        "🔥 *COUP DU JOUR* = tendance du moment"
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
        f"🔁 *Scan auto* : toutes les {SCAN_INTERVAL_MINUTES // 60}h\n"
        f"📦 *Progression* : [{bar}] {pct}%\n"
        f"   Marque {progress}/{len(BRANDS)}\n\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Marques* : {len(BRANDS)} surveillées\n"
        f"🤖 *IA* : Claude Sonnet — actif\n"
        f"👁️ *Vision* : activée sur articles hype\n"
        f"📡 *Sources* : eBay · Vinted"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🏷️ *Maisons surveillées*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for b in sorted(BRANDS):
        lines.append(f"  · {b}")
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"*{len(BRANDS)} maisons au total*")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔄 *Scan lancé*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 Claude analyse chaque article...\n"
        "_Résultats dans quelques instants_",
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
            "Tape /marques pour la liste complète",
            parse_mode="Markdown"
        )
        return

    brand = " ".join(context.args)
    brand_match = next((b for b in BRANDS if b.lower() == brand.lower()), None)

    if not brand_match:
        await update.message.reply_text(
            f"❌ *Marque non reconnue* : `{brand}`\n\n"
            f"Tape /marques pour la liste complète.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🔎 *Recherche en cours*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🏷️ Marque : *{brand_match}*\n"
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🤖 Claude analyse chaque article...\n"
        f"👁️ Vision activée sur articles hype\n\n"
        f"_Résultats dans quelques instants_",
        parse_mode="Markdown"
    )

    results = search_all_sources(brand_match)
    new_items = [r for r in results if not is_already_seen(r.get("url", ""))]

    if not new_items:
        await update.message.reply_text(
            f"⚠️ *Aucun résultat*\n\n"
            f"L'IA n'a retenu aucun article pour *{brand_match}*.\n"
            f"Réessaie plus tard.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"✅ *{len(new_items)} article(s)* sélectionné(s) pour *{brand_match}*",
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
        "🔬 *Diagnostic en cours...*",
        parse_mode="Markdown"
    )
    brand = "Hermès"
    lines = [
        f"🔬 *Diagnostic — {brand}*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"💶 {MIN_PRICE}€ – {MAX_PRICE}€\n",
    ]
    for name, fn in [("Vinted", search_vinted)]:
        try:
            res = fn(brand)
            if res:
                sample = res[0]
                lines.append(
                    f"✅ *{name}* : {len(res)} article(s) validé(s)\n"
                    f"   📌 {str(sample.get('title',''))[:45]}…\n"
                    f"   💰 {sample.get('price')}€\n"
                    f"   🤖 _{sample.get('ai_reason', '')[:60]}_"
                )
            else:
                lines.append(f"⚠️ *{name}* : aucun article retenu")
        except Exception as e:
            lines.append(f"❌ *{name}* : `{str(e)[:60]}`")
    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS
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
        lines = ["🏷️ *Maisons surveillées*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for b in sorted(BRANDS):
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
            f"📦 [{bar}] {pct}%\n"
            f"🤖 Claude : actif | 👁️ Vision : hype only",
            parse_mode="Markdown"
        )
    elif query.data == "do_help":
        await query.message.reply_text(
            "❓ *Commandes*\n"
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

    while True:
        try:
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
                first=60,
                name="scan_auto",
            )

            logger.info(
                f"🚀 Bot démarré — {len(BRANDS)} marques | "
                f"scan {SCAN_INTERVAL_MINUTES // 60}h | IA + vision hype"
            )

            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )

        except Exception as e:
            logger.warning(f"⚠️ Erreur, redémarrage dans 20s : {e}")
            time.sleep(20)
            continue
        break


if __name__ == "__main__":
    main()
