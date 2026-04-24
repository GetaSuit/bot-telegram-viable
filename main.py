"""
main.py — GetaSuit Sourcing Bot
Alertes en temps réel — Vinted + Vestiaire Collective
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
from scrapers import fetch_new, fetch_vinted_new, fetch_vestiaire_new
from database import init_db, is_seen, mark_seen

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Intervalle de surveillance en secondes (5 min)
WATCH_INTERVAL = 300
_watching = {"active": False}
_watch_task = {"task": None}


# ──────────────────────────────────────────
# KEEP ALIVE
# ──────────────────────────────────────────

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a):
        pass

def start_http():
    HTTPServer(("0.0.0.0", 10000), H).serve_forever()


# ──────────────────────────────────────────
# FORMATAGE ALERTE
# ──────────────────────────────────────────

def format_alert(item: dict) -> str:
    title = item.get("title", "?")
    brand = item.get("brand", "?")
    price = item.get("price", "?")
    size = item.get("size", "")
    source = item.get("source", "?")
    url = item.get("url", "")

    size_line = f"📐 *Taille* : {size}\n" if size else ""

    return (
        f"🔔 *NOUVELLE ANNONCE*\n\n"
        f"🏷️ *{brand}*\n"
        f"_{title}_\n\n"
        f"💰 *{price}€*\n"
        f"{size_line}"
        f"📦 {source}\n\n"
        f"🔗 [Voir l'annonce]({url})"
    )

def build_kbd(item: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Voir l'annonce", url=item.get("url", ""))],
        [
            InlineKeyboardButton("✅ Intéressant", callback_data="ok"),
            InlineKeyboardButton("❌ Ignorer", callback_data="skip"),
        ],
    ])

async def send_alert(bot, item: dict):
    text = format_alert(item)
    kbd = build_kbd(item)
    image = item.get("image")
    try:
        if image:
            await bot.send_photo(
                chat_id=CHAT_ID,
                photo=image,
                caption=text,
                parse_mode="Markdown",
                reply_markup=kbd,
            )
        else:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=kbd,
            )
    except Exception as e:
        logger.warning(f"[alert] {e}")
        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode="Markdown",
                reply_markup=kbd,
            )
        except Exception as e2:
            logger.error(f"[alert] fallback: {e2}")


# ──────────────────────────────────────────
# BOUCLE DE SURVEILLANCE
# ──────────────────────────────────────────

async def watch_loop(bot):
    """Surveille toutes les marques en rotation et alerte dès qu'un nouvel article apparaît."""
    logger.info("👁️ Surveillance démarrée")
    cursor = 0

    while _watching["active"]:
        brand = BRANDS[cursor % len(BRANDS)]
        cursor += 1

        try:
            items = fetch_new(brand)
            new_items = [i for i in items if not is_seen(i.get("id", i.get("url", "")))]

            for item in new_items:
                uid = item.get("id", item.get("url", ""))
                mark_seen(uid)
                await send_alert(bot, item)
                logger.info(f"🔔 Alerte envoyée : {item.get('title','')[:50]} — {item.get('price')}€")
                await asyncio.sleep(2)

        except Exception as e:
            logger.error(f"[watch] Erreur '{brand}': {e}")

        # Pause entre chaque marque
        await asyncio.sleep(WATCH_INTERVAL / len(BRANDS))

    logger.info("👁️ Surveillance arrêtée")


# ──────────────────────────────────────────
# COMMANDES
# ──────────────────────────────────────────

def brand_buttons() -> list:
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
    status = "🟢 Active" if _watching["active"] else "🔴 Inactive"
    buttons = [
        [
            InlineKeyboardButton("▶️ Activer la surveillance", callback_data="watch_on"),
            InlineKeyboardButton("⏹️ Désactiver", callback_data="watch_off"),
        ],
        [
            InlineKeyboardButton("🔎 Chercher maintenant", callback_data="search_now"),
            InlineKeyboardButton("🏷️ Les marques", callback_data="all_brands"),
        ],
        [
            InlineKeyboardButton("📊 Statut", callback_data="status"),
            InlineKeyboardButton("❓ Aide", callback_data="help"),
        ],
    ]

    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│     👑  GETASUIT SOURCING    │\n"
        "│     Alertes Luxe en Direct   │\n"
        "└──────────────────────────────┘\n\n"
        f"📡 *Surveillance* : {status}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Sources* : Vinted · Vestiaire\n"
        f"💶 *Budget* : {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ *Maisons* : {len(BRANDS)} surveillées\n"
        f"⏱️ *Check* : toutes les {WATCH_INTERVAL//60} min\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 *Active la surveillance pour recevoir\n"
        "les alertes en temps réel*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )

async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Active la surveillance."""
    if _watching["active"]:
        await update.message.reply_text("👁️ La surveillance est déjà active.")
        return
    _watching["active"] = True
    task = asyncio.create_task(watch_loop(context.bot))
    _watch_task["task"] = task
    await update.message.reply_text(
        "✅ *Surveillance activée*\n\n"
        f"Je surveille {len(BRANDS)} marques sur Vinted et Vestiaire.\n"
        f"Tu recevras une alerte dès qu'un nouvel article apparaît.\n\n"
        f"_Check toutes les {WATCH_INTERVAL//60} min_",
        parse_mode="Markdown",
    )

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Désactive la surveillance."""
    _watching["active"] = False
    if _watch_task.get("task"):
        _watch_task["task"].cancel()
    await update.message.reply_text(
        "⏹️ *Surveillance désactivée*\n\n"
        "Utilise /watch pour la réactiver.",
        parse_mode="Markdown",
    )

async def cmd_chercher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recherche manuelle immédiate sur une marque."""
    if not context.args:
        await update.message.reply_text(
            "🔎 Usage : `/chercher Hermès`\n\nOu choisis une marque :",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(brand_buttons()),
        )
        return

    brand = " ".join(context.args)
    match = next((b for b in BRANDS if b.lower() == brand.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ Marque `{brand}` non reconnue.\n/marques pour la liste.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🔎 Recherche *{match}* sur Vinted et Vestiaire...",
        parse_mode="Markdown",
    )

    items = fetch_new(match)
    new = [i for i in items if not is_seen(i.get("id", i.get("url", "")))]

    if not new:
        await update.message.reply_text(
            f"⚠️ Aucun nouvel article pour *{match}* pour le moment.\n"
            f"_Active la surveillance avec /watch pour les alertes automatiques_",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"🔔 *{len(new)} article(s) trouvé(s)* pour *{match}*",
        parse_mode="Markdown",
    )

    for item in new[:10]:
        mark_seen(item.get("id", item.get("url", "")))
        await send_alert(context.bot, item)
        await asyncio.sleep(1.5)

async def cmd_marques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🏷️ *{len(BRANDS)} maisons surveillées*\n\n"
        "👇 Clique pour une recherche immédiate",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(brand_buttons()),
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "🟢 Active" if _watching["active"] else "🔴 Inactive"
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│      📊  STATUT              │\n"
        "└──────────────────────────────┘\n\n"
        f"📡 *Surveillance* : {status}\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y à %H:%M')}\n\n"
        f"📦 Vinted · Vestiaire Collective\n"
        f"💶 {MIN_PRICE}€ – {MAX_PRICE}€\n"
        f"🏷️ {len(BRANDS)} maisons\n"
        f"⏱️ Check toutes les {WATCH_INTERVAL//60} min",
        parse_mode="Markdown",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "┌──────────────────────────────┐\n"
        "│      ❓  AIDE                │\n"
        "└──────────────────────────────┘\n\n"
        "▶️ /watch — Activer les alertes automatiques\n"
        "⏹️ /stop — Désactiver les alertes\n"
        "🔎 /chercher `<marque>` — Recherche immédiate\n"
        "🏷️ /marques — Liste cliquable\n"
        "📊 /status — État du bot\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Comment ça marche :*\n\n"
        "Lance `/watch` — le bot surveille Vinted\n"
        "et Vestiaire toutes les 5 min.\n"
        "Dès qu'un article correspondant à tes\n"
        "critères apparaît → tu reçois une alerte\n"
        "avec le nom, la marque, le prix et le lien.",
        parse_mode="Markdown",
    )


# ──────────────────────────────────────────
# CALLBACKS BOUTONS
# ──────────────────────────────────────────

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "watch_on":
        if not _watching["active"]:
            _watching["active"] = True
            task = asyncio.create_task(watch_loop(context.bot))
            _watch_task["task"] = task
        await q.message.reply_text(
            "✅ *Surveillance activée*\n\n"
            f"Je surveille {len(BRANDS)} marques.\n"
            "Tu recevras une alerte dès qu'un nouvel article apparaît.",
            parse_mode="Markdown",
        )

    elif d == "watch_off":
        _watching["active"] = False
        if _watch_task.get("task"):
            _watch_task["task"].cancel()
        await q.message.reply_text(
            "⏹️ *Surveillance désactivée*\n\n"
            "Utilise /watch pour la réactiver.",
            parse_mode="Markdown",
        )

    elif d == "search_now":
        await q.message.reply_text(
            "🔎 *Recherche par marque*\n\nChoisis ou tape `/chercher Hermès`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(brand_buttons()),
        )

    elif d == "all_brands":
        await q.message.reply_text(
            f"🏷️ *{len(BRANDS)} maisons*\n\n👇 Clique pour rechercher",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(brand_buttons()),
        )

    elif d.startswith("s_"):
        brand = d[2:]
        match = next((b for b in BRANDS if b == brand), None)
        if not match:
            return
        await q.message.reply_text(
            f"🔎 Recherche *{match}*...",
            parse_mode="Markdown",
        )
        items = fetch_new(match)
        new = [i for i in items if not is_seen(i.get("id", i.get("url", "")))]
        if not new:
            await q.message.reply_text(
                f"⚠️ Aucun nouvel article pour *{match}*.\n_Réessaie plus tard_",
                parse_mode="Markdown",
            )
            return
        await q.message.reply_text(
            f"🔔 *{len(new)} article(s)* pour *{match}*",
            parse_mode="Markdown",
        )
        for item in new[:10]:
            mark_seen(item.get("id", item.get("url", "")))
            await send_alert(context.bot, item)
            await asyncio.sleep(1.5)

    elif d == "status":
        status = "🟢 Active" if _watching["active"] else "🔴 Inactive"
        await q.message.reply_text(
            f"📡 *Surveillance* : {status}\n"
            f"🕐 {datetime.now().strftime('%H:%M')}\n"
            f"🏷️ {len(BRANDS)} maisons | ⏱️ {WATCH_INTERVAL//60} min",
            parse_mode="Markdown",
        )

    elif d == "help":
        await q.message.reply_text(
            "▶️ /watch — Alertes automatiques\n"
            "⏹️ /stop — Désactiver\n"
            "🔎 /chercher — Recherche immédiate\n"
            "🏷️ /marques — Liste\n"
            "📊 /status — État",
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
        BotCommand("watch", "▶️ Activer les alertes"),
        BotCommand("stop", "⏹️ Désactiver les alertes"),
        BotCommand("chercher", "🔎 Recherche immédiate"),
        BotCommand("marques", "🏷️ Liste des maisons"),
        BotCommand("status", "📊 État"),
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
            app.add_handler(CommandHandler("watch", cmd_watch))
            app.add_handler(CommandHandler("stop", cmd_stop))
            app.add_handler(CallbackQueryHandler(on_button))

            logger.info(f"🚀 Bot démarré — {len(BRANDS)} marques | Alertes temps réel")

            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )

        except Exception as e:
            logger.warning(f"⚠️ Redémarrage dans 20s : {e}")
            time.sleep(20)
            continue
        break


if __name__ == "__main__":
    main()
