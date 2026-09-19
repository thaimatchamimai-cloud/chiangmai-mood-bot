#!/usr/bin/env python3
"""A dependency-free Telegram bot for Anna's curated Chiang Mai places."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from catalog import CATEGORIES, CATEGORY_PARENT, GROUPS, MAIN_MENU
from database import CatalogDB


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "data" / "chiangmai.db"
SEED_FILE = BASE_DIR / "data" / "places.json"
BOT_TITLE = os.environ.get("BOT_TITLE", "Chiang Mai Mood")
WELCOME = (
    f"🌿 <b>{html.escape(BOT_TITLE)}</b>\n\n"
    "A curated collection of places in Chiang Mai: where to eat, drink matcha, "
    "book a massage, work out or escape into nature.\n\n"
    "Choose a category:"
)


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("chiangmai_bot")


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **payload: Any) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + method,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        network_timeout = max(30, int(payload.get("timeout", 0)) + 10)
        try:
            with urlopen(request, timeout=network_timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise TelegramAPIError(f"Telegram HTTP {exc.code}: {detail}") from exc
        except (URLError, socket.timeout) as exc:
            raise TelegramAPIError(f"Telegram network error: {exc}") from exc
        if not result.get("ok"):
            raise TelegramAPIError(result.get("description", "Unknown Telegram error"))
        return result.get("result")


def rows(items: list[dict[str, str]], size: int = 2) -> list[list[dict[str, str]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def callback_button(text: str, data: str) -> dict[str, str]:
    if len(data.encode("utf-8")) > 64:
        raise ValueError(f"Callback data exceeds Telegram's 64-byte limit: {data}")
    return {"text": text, "callback_data": data}


def main_keyboard(db: CatalogDB) -> dict[str, Any]:
    buttons: list[dict[str, str]] = []
    for item in MAIN_MENU:
        if "group" in item:
            slug = item["group"]
            group = GROUPS[slug]
            count = db.group_count(group["categories"])
            buttons.append(callback_button(f"{group['label']} · {count}", f"group:{slug}"))
        else:
            slug = item["category"]
            count = db.category_count(slug)
            buttons.append(
                callback_button(f"{CATEGORIES[slug]['label']} · {count}", f"cat:{slug}:0")
            )
    keyboard = rows(buttons, 2)
    keyboard.append([callback_button("🔎 Search", "search")])
    return {"inline_keyboard": keyboard}


def group_keyboard(db: CatalogDB, group_slug: str) -> dict[str, Any]:
    group = GROUPS[group_slug]
    buttons = [
        callback_button(
            f"{CATEGORIES[slug]['label']} · {db.category_count(slug)}",
            f"cat:{slug}:0",
        )
        for slug in group["categories"]
    ]
    keyboard = rows(buttons, 2)
    keyboard.append([callback_button("← Main Menu", "menu")])
    return {"inline_keyboard": keyboard}


def back_callback(category_slug: str) -> str:
    parent = CATEGORY_PARENT.get(category_slug)
    return f"group:{parent}" if parent else "menu"


def place_text(place: Any, index: int, total: int) -> str:
    parts = [f"<b>{html.escape(place['name'])}</b>"]
    if place["rating"] is not None:
        rating = str(place["rating"])
        review_text = ""
        if place["reviews"]:
            reviews = f"{place['reviews']:,}".replace(",", " ")
            review_text = f" · {reviews} reviews"
        parts.append(f"⭐ {rating}{review_text}")
    if place["place_type"]:
        parts.append(html.escape(place["place_type"]))
    if place["note"]:
        parts.append(f"\n{html.escape(place['note'])}")
    parts.append(f"\n<i>{index + 1} of {total}</i>")
    return "\n".join(parts)


def place_keyboard(place: Any, category_slug: str, index: int, total: int) -> dict[str, Any]:
    keyboard: list[list[dict[str, str]]] = [
        [{"text": "📍 Open in Google Maps", "url": place["map_url"]}]
    ]
    navigation: list[dict[str, str]] = []
    if index > 0:
        navigation.append(callback_button("← Previous", f"cat:{category_slug}:{index - 1}"))
    if index + 1 < total:
        navigation.append(callback_button("Next →", f"cat:{category_slug}:{index + 1}"))
    if navigation:
        keyboard.append(navigation)
    keyboard.append(
        [callback_button("← Categories", back_callback(category_slug))]
    )
    return {"inline_keyboard": keyboard}


def valid_maps_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    host = (parsed.hostname or "").casefold()
    return parsed.scheme in {"http", "https"} and (
        host == "maps.app.goo.gl"
        or host.endswith(".google.com")
        or host == "google.com"
        or host.endswith(".google.co.th")
    )


class ChiangMaiBot:
    def __init__(self, api: TelegramAPI, db: CatalogDB, admin_user_id: int | None):
        self.api = api
        self.db = db
        self.admin_user_id = admin_user_id
        self.user_state: dict[int, dict[str, Any]] = {}

    def send(self, chat_id: int, text: str, **kwargs: Any) -> Any:
        return self.api.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            link_preview_options={"is_disabled": True},
            **kwargs,
        )

    def edit(self, chat_id: int, message_id: int, text: str, **kwargs: Any) -> Any:
        return self.api.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            link_preview_options={"is_disabled": True},
            **kwargs,
        )

    def show_menu(self, chat_id: int, message_id: int | None = None) -> None:
        payload = {"reply_markup": main_keyboard(self.db)}
        if message_id is None:
            self.send(chat_id, WELCOME, **payload)
        else:
            self.edit(chat_id, message_id, WELCOME, **payload)

    def show_group(self, chat_id: int, message_id: int, group_slug: str) -> None:
        group = GROUPS.get(group_slug)
        if not group:
            self.show_menu(chat_id, message_id)
            return
        self.edit(
            chat_id,
            message_id,
            group["title"],
            reply_markup=group_keyboard(self.db, group_slug),
        )

    def show_category(
        self, chat_id: int, message_id: int, category_slug: str, index: int
    ) -> None:
        if category_slug not in CATEGORIES:
            self.show_menu(chat_id, message_id)
            return
        places = self.db.list_places(category_slug)
        if not places:
            self.edit(
                chat_id,
                message_id,
                f"{CATEGORIES[category_slug]['label']}\n\n"
                "No places here yet. More coming soon ✨",
                reply_markup={
                    "inline_keyboard": [
                        [callback_button("← Categories", back_callback(category_slug))]
                    ]
                },
            )
            return
        index = max(0, min(index, len(places) - 1))
        place = places[index]
        self.edit(
            chat_id,
            message_id,
            place_text(place, index, len(places)),
            reply_markup=place_keyboard(place, category_slug, index, len(places)),
        )

    def send_search_results(self, chat_id: int, query: str) -> None:
        matches = self.db.search_places(query)
        if not matches:
            self.send(
                chat_id,
                f"Nothing found for <b>{html.escape(query)}</b>. "
                "Try another name or keyword.",
                reply_markup={
                    "inline_keyboard": [[callback_button("← Main Menu", "menu_new")]]
                },
            )
            return
        keyboard = [
            [callback_button(place["name"][:48], f"one:{place['id']}")]
            for place in matches
        ]
        keyboard.append([callback_button("← Main Menu", "menu_new")])
        self.send(
            chat_id,
            f"🔎 Results for <b>{html.escape(query)}</b>:",
            reply_markup={"inline_keyboard": keyboard},
        )

    def show_single_place(self, chat_id: int, message_id: int, place_id: int) -> None:
        place = self.db.get_place(place_id)
        if not place:
            self.show_menu(chat_id, message_id)
            return
        text = place_text(place, 0, 1).replace("\n<i>1 of 1</i>", "")
        self.edit(
            chat_id,
            message_id,
            text,
            reply_markup={
                "inline_keyboard": [
                    [{"text": "📍 Open in Google Maps", "url": place["map_url"]}],
                    [callback_button("← Main Menu", "menu")],
                ]
            },
        )

    def is_admin(self, user_id: int) -> bool:
        return self.admin_user_id is not None and user_id == self.admin_user_id

    def start_add(self, chat_id: int, user_id: int) -> None:
        if not self.is_admin(user_id):
            self.send(
                chat_id,
                "Only the bot owner can add places. Your Telegram ID: "
                f"<code>{user_id}</code>",
            )
            return
        self.user_state[user_id] = {"mode": "add", "stage": "link"}
        self.send(chat_id, "Send the Google Maps link for the place.\n\n/cancel — cancel")

    def handle_add_text(self, chat_id: int, user_id: int, text: str) -> bool:
        state = self.user_state.get(user_id)
        if not state or state.get("mode") != "add":
            return False
        stage = state["stage"]
        if stage == "link":
            if not valid_maps_url(text):
                self.send(chat_id, "Please send a valid Google Maps link.")
                return True
            state["link"] = text.strip()
            state["stage"] = "name"
            self.send(chat_id, "What is this place called?")
        elif stage == "name":
            state["name"] = text.strip()
            state["stage"] = "category"
            category_buttons = [
                callback_button(meta["label"], f"ac:{slug}")
                for slug, meta in CATEGORIES.items()
            ]
            self.send(
                chat_id,
                "Choose a category:",
                reply_markup={"inline_keyboard": rows(category_buttons, 2)},
            )
        elif stage == "note":
            note = None if text.strip() == "-" else text.strip()
            place_id = self.db.add_place(
                name=state["name"],
                category_slug=state["category"],
                map_url=state["link"],
                note=note,
            )
            self.user_state.pop(user_id, None)
            self.send(
                chat_id,
                f"Done ✅ <b>{html.escape(state['name'])}</b> has been added. "
                f"Place ID: <code>{place_id}</code>",
                reply_markup=main_keyboard(self.db),
            )
        return True

    def handle_message(self, message: dict[str, Any]) -> None:
        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id", chat_id)
        text = (message.get("text") or "").strip()
        if not text:
            return
        if text == "/cancel":
            self.user_state.pop(user_id, None)
            self.send(chat_id, "Cancelled.", reply_markup=main_keyboard(self.db))
            return
        if self.handle_add_text(chat_id, user_id, text):
            return
        command = text.split()[0].split("@")[0]
        if command in {"/start", "/menu"}:
            self.show_menu(chat_id)
        elif command == "/search":
            query = text[len(text.split()[0]) :].strip()
            if query:
                self.send_search_results(chat_id, query)
            else:
                self.user_state[user_id] = {"mode": "search"}
                self.send(chat_id, "Type a place name or keyword:")
        elif command == "/add":
            self.start_add(chat_id, user_id)
        elif command == "/delete":
            if not self.is_admin(user_id):
                self.send(chat_id, "Only the bot owner can use this command.")
                return
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                self.send(chat_id, "Format: <code>/delete ID</code>")
                return
            deleted = self.db.deactivate_place(int(parts[1]))
            self.send(chat_id, "Place removed." if deleted else "No place found with that ID.")
        elif command == "/whoami":
            self.send(chat_id, f"Your Telegram ID: <code>{user_id}</code>")
        elif command == "/stats" and self.is_admin(user_id):
            self.send(chat_id, f"Places in the guide: <b>{self.db.total_places()}</b>.")
        elif self.user_state.get(user_id, {}).get("mode") == "search":
            self.user_state.pop(user_id, None)
            self.send_search_results(chat_id, text)
        else:
            self.send(
                chat_id,
                "Use the menu buttons or search by place name.",
                reply_markup=main_keyboard(self.db),
            )

    def handle_callback(self, query: dict[str, Any]) -> None:
        query_id = query["id"]
        data = query.get("data", "")
        message = query.get("message")
        user_id = query.get("from", {}).get("id")
        self.api.call("answerCallbackQuery", callback_query_id=query_id)
        if not message:
            return
        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        if data == "menu":
            self.show_menu(chat_id, message_id)
        elif data == "menu_new":
            self.show_menu(chat_id)
        elif data == "search":
            self.user_state[user_id] = {"mode": "search"}
            self.send(chat_id, "Type a place name or keyword:")
        elif data.startswith("group:"):
            self.show_group(chat_id, message_id, data.split(":", 1)[1])
        elif data.startswith("cat:"):
            _, slug, raw_index = data.split(":", 2)
            self.show_category(chat_id, message_id, slug, int(raw_index))
        elif data.startswith("one:"):
            self.show_single_place(chat_id, message_id, int(data.split(":", 1)[1]))
        elif data.startswith("ac:"):
            if not self.is_admin(user_id):
                return
            state = self.user_state.get(user_id)
            if not state or state.get("mode") != "add" or state.get("stage") != "category":
                return
            slug = data.split(":", 1)[1]
            if slug not in CATEGORIES:
                return
            state["category"] = slug
            state["stage"] = "note"
            self.send(
                chat_id,
                "Add a short personal note. If you do not need one, send <b>-</b>",
            )

    def handle_update(self, update: dict[str, Any]) -> None:
        if "message" in update:
            self.handle_message(update["message"])
        elif "callback_query" in update:
            self.handle_callback(update["callback_query"])


def prepare_db(path: Path) -> CatalogDB:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = CatalogDB(path)
    db.init_schema()
    db.seed_from_json(SEED_FILE)
    return db


def check_project() -> int:
    db = CatalogDB(":memory:")
    db.init_schema()
    inserted = db.seed_from_json(SEED_FILE)
    total = db.total_places()
    assert inserted == total
    assert total >= 50
    assert db.category_count("coffee") >= 15
    assert db.category_count("matcha") >= 5
    for item in MAIN_MENU:
        if "category" in item:
            callback_button("test", f"cat:{item['category']}:0")
    print(f"OK: {total} places, {len(CATEGORIES)} categories; database and menu work")
    db.close()
    return 0


def run_bot(db_path: Path) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print(
            "TELEGRAM_BOT_TOKEN is not set. Local check: python bot.py --check",
            file=sys.stderr,
        )
        return 2
    raw_admin_id = os.environ.get("ADMIN_USER_ID", "").strip()
    admin_user_id = int(raw_admin_id) if raw_admin_id else None
    db = prepare_db(db_path)
    api = TelegramAPI(token)
    bot = ChiangMaiBot(api, db, admin_user_id)
    me = api.call("getMe")
    api.call(
        "setMyCommands",
        commands=[
            {"command": "start", "description": "Open the guide"},
            {"command": "menu", "description": "Main menu"},
            {"command": "search", "description": "Search for a place"},
            {"command": "whoami", "description": "Show my Telegram ID"},
            {"command": "add", "description": "Add a place (owner only)"},
            {"command": "cancel", "description": "Cancel adding a place"},
        ],
    )
    log.info("Bot @%s started with %d places", me.get("username"), db.total_places())
    offset: int | None = None
    try:
        while True:
            try:
                updates = api.call(
                    "getUpdates",
                    offset=offset,
                    timeout=30,
                    allowed_updates=["message", "callback_query"],
                )
                for update in updates:
                    offset = update["update_id"] + 1
                    try:
                        bot.handle_update(update)
                    except Exception:
                        log.exception("Failed to handle update %s", update.get("update_id"))
            except TelegramAPIError:
                log.exception("Telegram API error; retrying in 3 seconds")
                time.sleep(3)
    except KeyboardInterrupt:
        log.info("Bot stopped")
    finally:
        db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Curated Chiang Mai Telegram guide")
    parser.add_argument("--check", action="store_true", help="validate data and exit")
    parser.add_argument(
        "--db", type=Path, default=Path(os.environ.get("DB_PATH", DEFAULT_DB))
    )
    args = parser.parse_args()
    return check_project() if args.check else run_bot(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
