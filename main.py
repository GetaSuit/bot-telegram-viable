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
)
from scrapers import search_vinted, search_vestiaire, search_all_sources
from database import init_db, is_already_seen, mark_as_seen

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


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
        meta_line = f"{l_icon} *Liquidité* : {liquidity}  ·  {r_icon} *Risque* : {risk}\n"

    return (
        f"{header}"
        f"{runway_line}"
        f"{collection_line}"
        f"{verdict_line}"
        f"🏷️ *{title}*\n\n"
        f"💰 *Prix* : {price}€\n"
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
# RECHERCHE (core)
# ──────────────────────────────────────────

async def run_search(bot, brand: str, chat_id: str):
    results = search_all_sources(brand)
    new_items = [r for r in results if not is_already_seen(r.get("url", ""))]

    if not new_items:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"┌──────────────────────────┐\n"
                f"│   ⚠️   AUCUN RÉSULTAT    │\n"
                f"└──────────────────────────┘\n\n"
                f"L'IA n'a retenu aucun article\n"
                f"pour *{brand}*.\n\n"
                f"_Réessaie dans quelques minutes_"
            ),
            parse_mode="Markdown",
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"┌──────────────────────────────┐\n"
            f"│  ✅  {len(new_items)} ARTICLE(S) TROUVÉ(S)  │\n"
            f"└──────────────────────────────┘\n\n"
            f"🏷️ *{brand}* — Sélection IA"
        ),
        parse_mode="Markdown",
    )

    for item in new_items[:15]:
        url = item.get("url", "")
        if url:
            mark_as_seen(url)
        await send_article(bot, item, brand)
        await asyncio.sleep(1.5)


# ──────────────────────────────────────────
# ENVOI ARTICLE
# ──────────────────────────────────────────

async def send_article(bot, item: dict, brand: str):
    text = format_article(item, brand)
    keyboard = build_keyboard(item)
    image = item.get("image")

    if item.get("is_hype") or item.get("is_runway"):
        try:
            emoji = "🎭" if item.get("is_runway") else "🔥"
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
# COMMANDES
# ──────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton("👑 Hermès", callback_data="search_Hermès"),
            InlineKeyboardButton("💎 Chanel", callback_data="search_Chanel"),
            InlineKeyboardButton("🌟 Dior", callback_data="search_Dior"),
        ],
        [
            InlineKeyboardButton("🖤 Louis Vuitton", callback_data="search_Louis Vuitton"),
            InlineKeyboardButton("✨ Gucci", callback_data="search_Gucci"),
            InlineKeyboardButton("🔥 Prada", callback_data="search_Prada"),
        ],
        [
            InlineKeyboardButton("⚡ Balenciaga", callback_data="search_Balenciaga"),
            InlineKeyboardButton("🏆 Brioni", callback_data="search_Brioni"),
            InlineKeyboardButton("💼 Tom Ford", callback_data="search_Tom Ford"),
        ],
        [
            InlineKeyboardButton("📋 Toutes les marques", callback_data="do_marques"),
            InlineKeyboardButton("🔎 Autre marque", callback_data="do_search_custom"),
        ],
        [
            InlineKeyboardButton("📊 Statut", callback_data="do_status"),
            InlineKeyboardButton("❓ Aide", callback_data="do_help"),
        ],
    ]

    text = (
        "┌──────────────────────────────┐\n"
        "│     👑  GETASUIT SOURCING    │\n"
        "│     Assistant IA Luxe        │\n"
        "└──────────────────────────────┘\n\n"
        "Bienvenue — Chaque article est analysé\n"
        "par Claude : *cote réelle · collections\n"
        "archives · profit potentiel*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Sources : *Vinted · Vestiaire*\n"
        f"💶 Budget : *{MIN_PRICE}€ – {MAX_PRICE}€*\n"
        f"🏷️ Maisons : *{len(BRANDS)} surveillées*\n"
        f"🤖 IA : *Claude Sonnet — actif*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 *Sélectionne une marque*"
    )

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "┌──────────────────────────────┐\n"
        "│      ❓  AIDE & COMMANDES    │\n"
        "└──────────────────────────────┘\n\n"
        "🔎 /chercher `<marque>`\n"
        "   _Recherche immédiate_\n"
        "   Ex : `/chercher Hermès`\n\n"
        "🏷️ /marques\n"
        "   _Liste cliquable des maisons_\n\n"
        "📊 /status\n"
        "   _État du bot_\n\n"
        "🔬 /test\\_sources\n"
        "   _Diagnostic des sources_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *Analyse IA par article :*\n\n"
        "• Détection particulier vs revendeur\n"
        "• Cote réelle (Vestiaire, RealReal)\n"
        "• Archives toutes les collections\n"
        "• Pièces de défilé identifiées\n"
        "• Profit net après commission 15%\n"
        "• Liquidité & niveau de risque\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎭 *PIÈCE DE DÉFILÉ* — collection identifiée\n"
        "🔥 *COUP DU JOUR* — tendance du moment"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "┌──────────────────────────────┐\n"
        "│      📊  STATUT DU BOT       │\n"
        "└──────────────────────────────┘\n\n"
        f"🟢 *Bot actif*\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Sources* : Vinted · Vestiaire\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Maisons* : {len(BRANDS)} surveillées\n"
        f"🤖 *IA* : Claude Sonnet\n"
        f"👁️ *Vision* : activée sur articles hype\n"
        f"🔄 *Scan auto* : désactivé\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "_Utilise /chercher pour lancer une recherche_"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = []
    row = []
    for brand in sorted(BRANDS):
        row.append(InlineKeyboardButton(brand, callback_data=f"search_{brand}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    text = (
        "┌──────────────────────────────┐\n"
        "│    🏷️  MAISONS SURVEILLÉES   │\n"
        "└──────────────────────────────┘\n\n"
        "👇 *Clique sur une marque pour lancer\n"
        "une recherche immédiate*\n\n"
        f"_{len(BRANDS)} maisons au total_"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cmd_chercher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        buttons = []
        row = []
        for brand in sorted(BRANDS):
            row.append(InlineKeyboardButton(brand, callback_data=f"search_{brand}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        await update.message.reply_text(
            "┌──────────────────────────────┐\n"
            "│     🔎  CHOISIR UNE MARQUE   │\n"
            "└──────────────────────────────┘\n\n"
            "👇 *Sélectionne une marque* ou tape :\n"
            "`/chercher Hermès`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    brand = " ".join(context.args)
    brand_match = next((b for b in BRANDS if b.lower() == brand.lower()), None)

    if not brand_match:
        await update.message.reply_text(
            f"❌ *Marque non reconnue* : `{brand}`\n\n"
            f"Tape /marques pour voir la liste complète.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"┌──────────────────────────────┐\n"
        f"│     🔎  RECHERCHE EN COURS   │\n"
        f"└──────────────────────────────┘\n\n"
        f"🏷️ *{brand_match}*\n"
        f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"📦 Vinted · Vestiaire Collective\n"
        f"🤖 Claude analyse chaque article...\n\n"
        f"_Résultats dans quelques instants_",
        parse_mode="Markdown",
    )
    await run_search(context.bot, brand_match, update.message.chat_id)

async def cmd_test_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│   🔬  DIAGNOSTIC SOURCES     │\n"
        "└──────────────────────────────┘\n\n"
        "_Test en cours..._",
        parse_mode="Markdown",
    )
    brand = "Hermès"
    lines = [
        f"🔬 *Diagnostic — {brand}*",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💶 {MIN_PRICE}€ – {MAX_PRICE}€\n",
    ]
    for name, fn in [("Vinted", search_vinted), ("Vestiaire", search_vestiaire)]:
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

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS BOUTONS
# ──────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("search_"):
        brand = data[7:]
        brand_match = next((b for b in BRANDS if b == brand), None)
        if not brand_match:
            await query.message.reply_text(
                f"❌ Marque non reconnue : `{brand}`",
                parse_mode="Markdown"
            )
            return
        await query.message.reply_text(
            f"┌──────────────────────────────┐\n"
            f"│     🔎  RECHERCHE EN COURS   │\n"
            f"└──────────────────────────────┘\n\n"
            f"🏷️ *{brand_match}*\n"
            f"💶 Budget : {MIN_PRICE}€ – {MAX_PRICE}€\n"
            f"📦 Vinted · Vestiaire Collective\n"
            f"🤖 Claude analyse chaque article...\n\n"
            f"_Résultats dans quelques instants_",
            parse_mode="Markdown",
        )
        await run_search(context.bot, brand_match, query.message.chat_id)

    elif data == "do_search_custom":
        await query.message.reply_text(
            "🔎 *Recherche par marque*\n\n"
            "Tape la commande :\n"
            "`/chercher NomDeLaMarque`\n\n"
            "Ex : `/chercher Saint Laurent`",
            parse_mode="Markdown",
        )

    elif data == "do_marques":
        buttons = []
        row = []
        for brand in sorted(BRANDS):
            row.append(InlineKeyboardButton(brand, callback_data=f"search_{brand}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        await query.message.reply_text(
            "┌──────────────────────────────┐\n"
            "│    🏷️  MAISONS SURVEILLÉES   │\n"
            "└──────────────────────────────┘\n\n"
            "👇 *Clique sur une marque*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )

    elif data == "do_status":
        await query.message.reply_text(
            "┌──────────────────────────────┐\n"
            "│      📊  STATUT DU BOT       │\n"
            "└──────────────────────────────┘\n\n"
            f"🟢 Bot actif\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n"
            f"📦 Vinted · Vestiaire\n"
            f"🤖 IA Claude : actif\n"
            f"🔄 Scan auto : désactivé",
            parse_mode="Markdown",
        )

    elif data == "do_help":
        await query.message.reply_text(
            "┌──────────────────────────────┐\n"
            "│      ❓  COMMANDES           │\n"
            "└──────────────────────────────┘\n\n"
            "🔎 /chercher — Recherche par marque\n"
            "🏷️ /marques — Liste cliquable\n"
            "📊 /status — État du bot\n"
            "🔬 /test\\_sources — Diagnostic\n"
            "❓ /help — Aide complète",
            parse_mode="Markdown",
        )

    elif data == "interested":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Sauvegardé", callback_data="noop")
            ]])
        )

    elif data == "ignore":
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑️ Ignoré", callback_data="noop")
            ]])
        )


# ──────────────────────────────────────────
# SETUP COMMANDES TELEGRAM
# ──────────────────────────────────────────

async def setup_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 Accueil & recherche rapide"),
        BotCommand("chercher", "🔎 Rechercher une marque"),
        BotCommand("marques", "🏷️ Liste des maisons surveillées"),
        BotCommand("status", "📊 État du bot"),
        BotCommand("test_sources", "🔬 Diagnostic sources"),
        BotCommand("help", "❓ Aide & commandes"),
    ])


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
            app = (
                Application.builder()
                .token(TELEGRAM_TOKEN)
                .post_init(setup_commands)
                .build()
            )

            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("help", cmd_help))
            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("marques", cmd_marques))
            app.add_handler(CommandHandler("chercher", cmd_chercher))
            app.add_handler(CommandHandler("test_sources", cmd_test_sources))
            app.add_handler(CallbackQueryHandler(button_callback))

            logger.info(
                f"🚀 Bot démarré — {len(BRANDS)} marques | "
                f"Vinted + Vestiaire | IA Claude"
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
