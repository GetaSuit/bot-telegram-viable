"""
main.py — GetaSuit Sourcing Bot
python-telegram-bot 20.6 | Render.com
"""

import logging
import asyncio
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import TELEGRAM_TOKEN, CHAT_ID, BRANDS, MIN_PRICE, MAX_PRICE
from scrapers import search_all, search_vinted, search_vestiaire
from database import init_db, is_seen, mark_seen

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────
# KEEP ALIVE
# ──────────────────────────────────────────

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

def start_http():
    HTTPServer(("0.0.0.0", 10000), HealthHandler).serve_forever()


# ──────────────────────────────────────────
# FORMATAGE
# ──────────────────────────────────────────

def fmt(item: dict, brand: str) -> str:
    title = item.get("title", "?")
    price = item.get("price", "?")
    source = item.get("source", "?")
    url = item.get("url", "")
    reason = item.get("ai_reason", "")
    verdict = item.get("ai_verdict", "correct")
    mv = item.get("market_value")
    profit = item.get("profit_net")

    icons = {"excellent": "🏆", "bon": "✅", "correct": "👍", "faible": "💤", "suspect": "⚠️"}
    icon = icons.get(verdict, "🔍")

    reason_line = f"{icon} _{reason}_\n\n" if reason else ""

    profit_line = ""
    if mv and profit and profit > 0:
        profit_line = (
            f"💹 *Revente* : ~{mv:.0f}€\n"
            f"📊 *Profit net* : +{profit:.0f}€\n"
        )
    elif mv:
        profit_line = f"💹 *Valeur marché* : ~{mv:.0f}€\n"

    return (
        f"{reason_line}"
        f"🏷️ *{title}*\n\n"
        f"💰 *Prix* : {price}€\n"
        f"{profit_line}"
        f"📦 *Source* : {source}\n\n"
        f"🔗 [Voir l'annonce]({url})"
    )

def kbd(item: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Voir l'annonce", url=item.get("url", ""))],
        [
            InlineKeyboardButton("✅ Intéressant", callback_data="ok"),
            InlineKeyboardButton("❌ Ignorer", callback_data="skip"),
        ],
    ])

async def send(bot, item: dict, brand: str):
    text = fmt(item, brand)
    image = item.get("image")
    keyboard = kbd(item)
    try:
        if image:
            await bot.send_photo(
                chat_id=CHAT_ID, photo=image,
                caption=text, parse_mode="Markdown",
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID, text=text,
                parse_mode="Markdown", reply_markup=keyboard,
            )
    except Exception as e:
        logger.warning(f"[send] {e}")
        try:
            await bot.send_message(
                chat_id=CHAT_ID, text=text,
                parse_mode="Markdown", reply_markup=keyboard,
            )
        except Exception as e2:
            logger.error(f"[send] fallback: {e2}")


# ──────────────────────────────────────────
# RECHERCHE CORE
# ──────────────────────────────────────────

async def do_search(bot, brand: str, chat_id):
    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"┌──────────────────────────────┐\n"
            f"│     🔎  RECHERCHE EN COURS   │\n"
            f"└──────────────────────────────┘\n\n"
            f"🏷️ *{brand}*\n"
            f"💶 {MIN_PRICE}€ – {MAX_PRICE}€\n"
            f"📦 Vinted · Vestiaire Collective\n"
            f"🤖 Analyse IA en cours...\n\n"
            f"_Résultats dans quelques instants_"
        ),
        parse_mode="Markdown",
    )

    items = search_all(brand)
    new = [i for i in items if not is_seen(i.get("url", ""))]

    if not new:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"┌──────────────────────────┐\n"
                f"│   ⚠️  AUCUN RÉSULTAT     │\n"
                f"└──────────────────────────┘\n\n"
                f"Aucun article retenu pour *{brand}*.\n"
                f"_Réessaie dans quelques minutes_"
            ),
            parse_mode="Markdown",
        )
        return

    await bot.send_message(
        chat_id=chat_id,
        text=f"✅ *{len(new)} article(s)* sélectionné(s) pour *{brand}*",
        parse_mode="Markdown",
    )

    for item in new[:15]:
        mark_seen(item.get("url", ""))
        await send(bot, item, brand)
        await asyncio.sleep(1.5)


# ──────────────────────────────────────────
# COMMANDES
# ──────────────────────────────────────────

def marques_buttons() -> list:
    buttons = []
    row = []
    for b in sorted(BRANDS):
        row.append(InlineKeyboardButton(b, callback_data=f"s_{b}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return buttons

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    buttons = [
        [
            InlineKeyboardButton("👑 Hermès", callback_data="s_Hermès"),
            InlineKeyboardButton("💎 Chanel", callback_data="s_Chanel"),
            InlineKeyboardButton("🌟 Dior", callback_data="s_Dior"),
        ],
        [
            InlineKeyboardButton("🖤 Louis Vuitton", callback_data="s_Louis Vuitton"),
            InlineKeyboardButton("✨ Gucci", callback_data="s_Gucci"),
            InlineKeyboardButton("🔥 Tom Ford", callback_data="s_Tom Ford"),
        ],
        [
            InlineKeyboardButton("⚡ Balenciaga", callback_data="s_Balenciaga"),
            InlineKeyboardButton("🏆 Brioni", callback_data="s_Brioni"),
            InlineKeyboardButton("💼 Lanvin", callback_data="s_Lanvin"),
        ],
        [
            InlineKeyboardButton("📋 Toutes les marques", callback_data="all_brands"),
            InlineKeyboardButton("🔎 Autre marque", callback_data="custom"),
        ],
        [
            InlineKeyboardButton("📊 Statut", callback_data="status"),
            InlineKeyboardButton("❓ Aide", callback_data="help"),
        ],
    ]
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│     👑  GETASUIT SOURCING    │\n"
        "│     Assistant IA Luxe        │\n"
        "└──────────────────────────────┘\n\n"
        "Chaque article est analysé par Claude :\n"
        "*cote réelle · profit · authenticité*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Sources* : Vinted · Vestiaire\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Maisons* : {len(BRANDS)} surveillées\n"
        f"🤖 *IA* : Claude Sonnet\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 *Sélectionne une marque*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│    🏷️  MAISONS SURVEILLÉES   │\n"
        "└──────────────────────────────┘\n\n"
        f"👇 *Clique pour lancer une recherche*\n_{len(BRANDS)} maisons_",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(marques_buttons()),
    )

async def cmd_chercher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🔎 Usage : `/chercher Hermès`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(marques_buttons()),
        )
        return
    brand = " ".join(context.args)
    match = next((b for b in BRANDS if b.lower() == brand.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ Marque `{brand}` non reconnue.\nTape /marques pour la liste.",
            parse_mode="Markdown",
        )
        return
    await do_search(context.bot, match, update.message.chat_id)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│      📊  STATUT DU BOT       │\n"
        "└──────────────────────────────┘\n\n"
        f"🟢 *Bot actif*\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
        f"📦 Vinted · Vestiaire Collective\n"
        f"💶 {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ {len(BRANDS)} maisons\n"
        f"🤖 IA Claude : actif\n"
        f"🔄 Scan auto : désactivé",
        parse_mode="Markdown",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│      ❓  AIDE                │\n"
        "└──────────────────────────────┘\n\n"
        "🔎 /chercher `<marque>` — Recherche immédiate\n"
        "🏷️ /marques — Liste cliquable\n"
        "📊 /status — État du bot\n"
        "🔬 /test — Diagnostic\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🤖 *L'IA analyse chaque article :*\n"
        "• Valeur marché réelle\n"
        "• Profit net estimé\n"
        "• Authenticité\n"
        "• Tendance actuelle",
        parse_mode="Markdown",
    )

async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔬 Diagnostic en cours...", parse_mode="Markdown")
    brand = "Tom Ford"
    lines = [f"🔬 *Diagnostic — {brand}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
    for name, fn in [("Vinted", search_vinted), ("Vestiaire", search_vestiaire)]:
        try:
            res = fn(brand)
            if res:
                s = res[0]
                lines.append(
                    f"✅ *{name}* : {len(res)} article(s)\n"
                    f"   📌 {s.get('title','')[:40]}…\n"
                    f"   💰 {s.get('price')}€\n"
                    f"   🤖 _{s.get('ai_reason','')[:50]}_"
                )
            else:
                lines.append(f"⚠️ *{name}* : 0 résultat")
        except Exception as e:
            lines.append(f"❌ *{name}* : `{str(e)[:50]}`")
    lines.append(f"\n🕐 {datetime.now().strftime('%H:%M:%S')}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ──────────────────────────────────────────
# CALLBACKS
# ──────────────────────────────────────────

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d.startswith("s_"):
        brand = d[2:]
        match = next((b for b in BRANDS if b == brand), None)
        if match:
            await do_search(context.bot, match, q.message.chat_id)

    elif d == "all_brands":
        await q.message.reply_text(
            "🏷️ *Toutes les maisons*\n\n👇 Clique pour rechercher",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(marques_buttons()),
        )

    elif d == "custom":
        await q.message.reply_text(
            "🔎 Tape : `/chercher NomMarque`\nEx : `/chercher Saint Laurent`",
            parse_mode="Markdown",
        )

    elif d == "status":
        await q.message.reply_text(
            f"📊 *Statut*\n🟢 Actif | 🕐 {datetime.now().strftime('%H:%M')}\n"
            f"📦 Vinted · Vestiaire | 🤖 IA Claude",
            parse_mode="Markdown",
        )

    elif d == "help":
        await q.message.reply_text(
            "🔎 /chercher — Recherche\n"
            "🏷️ /marques — Liste\n"
            "📊 /status — État\n"
            "🔬 /test — Diagnostic",
            parse_mode="Markdown",
        )

    elif d == "ok":
        await q.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⭐ Sauvegardé", callback_data="noop")
            ]])
        )

    elif d == "skip":
        await q.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑️ Ignoré", callback_data="noop")
            ]])
        )


# ──────────────────────────────────────────
# SETUP COMMANDES
# ──────────────────────────────────────────

async def setup_commands(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🏠 Accueil"),
        BotCommand("chercher", "🔎 Rechercher une marque"),
        BotCommand("marques", "🏷️ Liste des maisons"),
        BotCommand("status", "📊 État du bot"),
        BotCommand("test", "🔬 Diagnostic"),
        BotCommand("help", "❓ Aide"),
    ])


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

def main():
    threading.Thread(target=start_http, daemon=True).start()
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
            app.add_handler(CommandHandler("test", cmd_test))
            app.add_handler(CallbackQueryHandler(on_button))

            logger.info(f"🚀 Bot démarré — {len(BRANDS)} marques | Vinted + Vestiaire | IA Claude")

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
