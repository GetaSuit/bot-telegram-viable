"""
main.py — Bot Telegram Sourcing Luxe (version corrigée boutons + photos)
"""

import logging
import asyncio
import threading
import hashlib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode

import config
import database as db
from scrapers import scrape_all
from config import (
    ALLOWED_KEYWORDS, FORBIDDEN_KEYWORDS, MIN_BUY_PRICE, MAX_BUY_PRICE,
    TELEGRAM_TOKEN, CHAT_ID, SCAN_INTERVAL_MIN,
    ALL_BRANDS, FORBIDDEN_MATERIALS,
    get_tier, estimated_sell_price, margin_pct, is_pepite,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger(__name__)

stats = {"scans": 0, "articles_found": 0, "pepites_found": 0, "last_scan": None}
last_scan_results: list[dict] = []
url_store: dict[str, str] = {}  # hash -> url

PLATFORM_EMOJI = {"Vinted": "🟢", "Vestiaire Collective": "⚫", "eBay": "🔵", "Leboncoin": "🟠"}
TIER_LABEL = {"T1": "⭐ Sartorial", "T2": "✦ Grand luxe", "T3": "◆ Luxe"}


# ── Serveur HTTP minimal ──────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass

def run_health_server():
    HTTPServer(("0.0.0.0", 10000), HealthHandler).serve_forever()


# ── Utilitaires ───────────────────────────────────────────

def short_id(url: str) -> str:
    """Génère un ID court depuis une URL pour les boutons Telegram (max 64 chars)"""
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    url_store[h] = url
    return h

def get_url(h: str) -> str:
    return url_store.get(h, "")


# ── Filtrage ──────────────────────────────────────────────

def _has_forbidden_material(item):
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    return any(m in text for m in FORBIDDEN_MATERIALS)

def _is_allowed_category(item):
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    # Rejette si mot interdit trouvé
    if any(k in text for k in FORBIDDEN_KEYWORDS):
        return False
    # Accepte si mot autorisé trouvé (ou si aucun filtre ne s'applique)
    return any(k in text for k in ALLOWED_KEYWORDS)

def _price_ok(item):
    return MIN_BUY_PRICE <= item.get("price", 0) <= MAX_BUY_PRICE

def _size_ok(item):
    size = item.get("size", "").strip()
    if not size:
        return True
    return any(s.lower() in size.lower() for s in config.SIZES_MEN + config.SIZES_WOMEN)

def _enrich(item):
    tier = get_tier(item.get("brand", ""))
    buy  = item["price"]
    item["tier"]           = tier
    item["sell_estimated"] = estimated_sell_price(buy, tier)
    item["margin_pct"]     = margin_pct(buy, tier)
    item["pepite"]         = is_pepite(buy, tier)
    return item

def filter_and_enrich(items):
    out = []
    for it in items:
        if _has_forbidden_material(it): continue
        if not _is_allowed_category(it): continue
        if not _price_ok(it): continue
        if not _size_ok(it): continue
        if db.is_seen(it["url"]): continue
        out.append(_enrich(it))
    return out


# ── Formatage ─────────────────────────────────────────────

def format_item_message(item):
    pep  = "🔥 *PÉPITE DÉTECTÉE* 🔥\n\n" if item["pepite"] else ""
    pl   = PLATFORM_EMOJI.get(item["platform"], "•")
    tier = TIER_LABEL.get(item["tier"], "")
    msg  = (f"{pep}*{item['title'][:100]}*\n\n{pl} {item['platform']}  |  {tier}\n"
            f"💰 Achat : *{item['price']:.0f} €*\n"
            f"📈 Revente estimée : *{item['sell_estimated']} €*\n"
            f"📊 Marge : *+{item['margin_pct']}%*\n")
    if item.get("size"):
        msg += f"📐 Taille : {item['size']}\n"
    msg += f"\n🔗 [Voir l'article]({item['url']})"
    return msg

def item_keyboard(item):
    uid = short_id(item["url"])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Favori", callback_data=f"fav|{uid}"),
        InlineKeyboardButton("🔗 Ouvrir", url=item["url"]),
    ]])


# ── Envoi alerte ──────────────────────────────────────────

async def send_item_alert(app, item):
    text = format_item_message(item)
    kb   = item_keyboard(item)
    sent = False

    # Tente d'envoyer avec photo
    image_url = item.get("image_url", "")
    if image_url and image_url.startswith("http"):
        try:
            await app.bot.send_photo(
                chat_id=CHAT_ID,
                photo=image_url,
                caption=text[:1024],
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
            sent = True
        except Exception as e:
            log.warning(f"Photo échouée ({item['platform']}): {e}")

    # Fallback texte seul
    if not sent:
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
                disable_web_page_preview=False,
            )
            sent = True
        except Exception as e:
            log.error(f"Envoi texte échoué: {e}")

    if sent:
        db.mark_seen(item["url"], item["title"])


# ── Scan ──────────────────────────────────────────────────

async def run_scan(app, brands=None, silent=False):
    global last_scan_results
    target = brands or ALL_BRANDS
    stats["scans"] += 1
    stats["last_scan"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    if not silent:
        await app.bot.send_message(CHAT_ID,
            f"🔍 Scan en cours sur {len(target)} marques...\nPlateformes : eBay · Vestiaire")
    pepites, autres = [], []
    for brand in target:
        try:
            loop = asyncio.get_event_loop()
            raw  = await loop.run_in_executor(None, scrape_all, brand, MAX_BUY_PRICE)
            filtered = [_enrich(it) for it in raw
                       if not _has_forbidden_material(it)
                       and _is_allowed_category(it)
                       and _price_ok(it)
                       and not db.is_seen(it["url"])]
            for it in filtered:
                (pepites if it["pepite"] else autres).append(it)
        except Exception as e:
            log.error(f"Erreur scan {brand}: {e}")
    pepites.sort(key=lambda x: x["margin_pct"], reverse=True)
    autres.sort(key=lambda x: x["margin_pct"], reverse=True)
    ordered = pepites + autres
    last_scan_results = ordered
    stats["articles_found"] += len(ordered)
    stats["pepites_found"]  += len(pepites)
    if not ordered:
        if not silent:
            await app.bot.send_message(CHAT_ID, "✅ Scan terminé — aucun nouvel article.")
        return
    await app.bot.send_message(CHAT_ID,
        f"✅ *Scan terminé*\n\n📦 Articles : *{len(ordered)}*\n🔥 Pépites : *{len(pepites)}*",
        parse_mode=ParseMode.MARKDOWN)
    for it in pepites[:10]:
        await send_item_alert(app, it); await asyncio.sleep(0.8)
    for it in autres[:20]:
        await send_item_alert(app, it); await asyncio.sleep(0.8)

async def auto_scan_job(context: ContextTypes.DEFAULT_TYPE):
    await run_scan(context.application, silent=True)


# ── Commandes ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👔 *Bot Sourcing Luxe*\n\nChat ID : `{update.effective_chat.id}`\n\n"
        f"/scan — Scan immédiat\n/pepites — Pépites du dernier scan\n"
        f"/marque Brioni — Cherche une marque\n/favoris — Tes favoris\n"
        f"/stats — Statistiques\n/reset — Vide le cache",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Scan lancé...")
    asyncio.create_task(run_scan(ctx.application))

async def cmd_pepites(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    peps = [it for it in last_scan_results if it.get("pepite")]
    if not peps:
        await update.message.reply_text("Aucune pépite. Lance /scan pour actualiser.")
        return
    await update.message.reply_text(f"🔥 *{len(peps)} pépite(s) :*", parse_mode=ParseMode.MARKDOWN)
    for it in peps[:10]:
        await send_item_alert(ctx.application, it); await asyncio.sleep(0.8)

async def cmd_marque(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage : /marque Brioni"); return
    brand = " ".join(ctx.args)
    await update.message.reply_text(f"🔍 Recherche *{brand}*...", parse_mode=ParseMode.MARKDOWN)
    loop = asyncio.get_event_loop()
    raw  = await loop.run_in_executor(None, scrape_all, brand, MAX_BUY_PRICE)
    filtered = [_enrich(it) for it in raw
                if not _has_forbidden_material(it)
                and _is_allowed_category(it)
                and _price_ok(it)
                and not db.is_seen(it["url"])]
    filtered.sort(key=lambda x: x["margin_pct"], reverse=True)
    if not filtered:
        await update.message.reply_text(f"Aucun article pour *{brand}*.", parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text(f"✅ *{len(filtered)} article(s) :*", parse_mode=ParseMode.MARKDOWN)
    for it in filtered[:8]:
        await send_item_alert(ctx.application, it); await asyncio.sleep(0.8)

async def cmd_favoris(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    favs = db.list_favorites()
    if not favs:
        await update.message.reply_text("Pas encore de favoris."); return
    await update.message.reply_text(f"⭐ *{len(favs)} favori(s) :*", parse_mode=ParseMode.MARKDOWN)
    for it in favs:
        uid = short_id(it["url"])
        text = (f"*{it['title'][:80]}*\n💰 {it['price']:.0f}€ → ~{it.get('sell_estimated','?')}€  "
                f"📊 +{it.get('margin_pct','?')}%\n🔗 [Voir]({it['url']})")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Retirer", callback_data=f"unfav|{uid}"),
            InlineKeyboardButton("🔗 Ouvrir", url=it["url"]),
        ]])
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        await asyncio.sleep(0.5)

async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📊 *Statistiques*\n\n🔍 Scans : {stats['scans']}\n📦 Articles : {stats['articles_found']}\n"
        f"🔥 Pépites : {stats['pepites_found']}\n⭐ Favoris : {len(db.list_favorites())}\n"
        f"🕐 Dernier scan : {stats['last_scan'] or 'jamais'}\n⏱ Auto toutes les {SCAN_INTERVAL_MIN} min",
        parse_mode=ParseMode.MARKDOWN)

async def cmd_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db.clear_seen()
    await update.message.reply_text("✅ Cache vidé.")

async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    if data.startswith("fav|"):
        _, uid = data.split("|", 1)
        url  = get_url(uid)
        item = next((it for it in last_scan_results if it["url"] == url), {"url": url, "title": url[:40], "price": 0})
        if db.add_favorite(item):
            await query.edit_message_reply_markup(InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Ajouté", callback_data="noop"),
                InlineKeyboardButton("🔗 Ouvrir", url=url),
            ]]))
    elif data.startswith("unfav|"):
        _, uid = data.split("|", 1)
        url = get_url(uid)
        db.remove_favorite(url)
        await query.edit_message_reply_markup(InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Retiré", callback_data="noop"),
        ]]))


# ── Lancement ─────────────────────────────────────────────

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    log.info("Serveur HTTP démarré sur le port 10000")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("scan",    cmd_scan))
    app.add_handler(CommandHandler("pepites", cmd_pepites))
    app.add_handler(CommandHandler("marque",  cmd_marque))
    app.add_handler(CommandHandler("favoris", cmd_favoris))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.job_queue.run_repeating(auto_scan_job, interval=SCAN_INTERVAL_MIN * 60, first=60)
    log.info(f"Bot démarré — scan toutes les {SCAN_INTERVAL_MIN} min")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
