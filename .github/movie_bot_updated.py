import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

# ============================================================
# MAIN MENU SETTINGS
# ============================================================
MAIN_BUTTONS = [
    {"key": "latest", "text": "🎬 Latest Malayalam Movies", "type": "catalog"},
    {"key": "dubbed", "text": "🎥 Malayalam Dubbed Movies", "type": "catalog"},
    {"key": "request", "text": "📝 Request Menu", "type": "request"},
]
MAIN_MENU_COLUMNS = 1
YEAR_MENU_COLUMNS = 2
MOVIE_MENU_COLUMNS = 2
REQUEST_MENU_TEXT = "📝 Movie Request Menu\n\nChoose a button below."

# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
DATABASE_NAME = os.getenv("DATABASE_NAME", "movie_bot").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing.")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI is missing.")
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS is missing.")

mongo = AsyncIOMotorClient(MONGODB_URI)
db = mongo[DATABASE_NAME]
years_col = db["years"]
movies_col = db["movies"]
request_buttons_col = db["request_buttons"]
settings_col = db["settings"]
bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ============================================================
# BUTTON TEXTS
# ============================================================
SAVE_TEXT = "💾 Save Message"
CANCEL_TEXT = "❌ Cancel"
BACK_MAIN_TEXT = "⬅️ Go Back"
BACK_YEARS_TEXT = "⬅️ Back to Years"
BACK_ACTION_TEXT = "⬅️ Back"
BACK_LAYOUT_TEXT = "⬅️ Back from Layout"
ADD_YEAR_TEXT = "➕ Add Year"
ADD_MOVIE_TEXT = "➕ Add Movie"
ADD_REQUEST_BUTTON_TEXT = "➕ Add Button"
MANAGE_BUTTONS_TEXT = "⚙️ Manage Buttons"
LAYOUT_SETUP_TEXT = "📐 Layout Setup"
DELETE_BUTTON_TEXT = "🗑 Delete Button"
RENAME_BUTTON_TEXT = "✏️ Rename Button"
EDIT_MESSAGE_TEXT = "📝 Edit Message"
DELETE_MESSAGE_TEXT = "🧹 Delete Message"
ADD_MESSAGE_TEXT = "➕ Add Message"
MOVE_UP_TEXT = "⬆️ Move Up"
MOVE_DOWN_TEXT = "⬇️ Move Down"
MOVE_TOP_TEXT = "⏫ Move to Top"
MOVE_BOTTOM_TEXT = "⏬ Move to Bottom"
MOVE_POSITION_TEXT = "🔢 Move to Position"
CONFIRM_DELETE_TEXT = "✅ Confirm Delete"
COLUMN_OPTIONS = [f"{n} Button(s) Per Row" for n in range(1, 6)]

# ============================================================
# STATES
# ============================================================
class AdminFlow(StatesGroup):
    waiting_year = State()
    waiting_movie_name = State()
    waiting_request_button_name = State()
    collecting_content = State()
    selecting_manage_item = State()
    managing_item = State()
    waiting_rename = State()
    waiting_position = State()
    waiting_columns = State()
    layout_select_item = State()
    layout_select_position = State()
    edit_message_menu = State()
    edit_select_item = State()
    waiting_message_number = State()

# ============================================================
# KEYBOARD AND DATABASE HELPERS
# ============================================================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def make_keyboard(labels, columns=1, footer=None):
    columns = max(1, min(5, int(columns)))
    rows = [[KeyboardButton(text=str(x)) for x in labels[i:i + columns]]
            for i in range(0, len(labels), columns)]
    for label in footer or []:
        rows.append([KeyboardButton(text=label)])
    return ReplyKeyboardMarkup(keyboard=rows or [[KeyboardButton(text=BACK_MAIN_TEXT)]], resize_keyboard=True)


def main_menu():
    return make_keyboard([x["text"] for x in MAIN_BUTTONS], MAIN_MENU_COLUMNS)


def cancel_menu():
    return make_keyboard([CANCEL_TEXT])


def collect_menu():
    return make_keyboard([SAVE_TEXT, CANCEL_TEXT])


def action_menu():
    return make_keyboard([
        DELETE_BUTTON_TEXT, RENAME_BUTTON_TEXT, EDIT_MESSAGE_TEXT,
        DELETE_MESSAGE_TEXT, MOVE_UP_TEXT, MOVE_DOWN_TEXT,
        MOVE_TOP_TEXT, MOVE_BOTTOM_TEXT, MOVE_POSITION_TEXT,
        BACK_ACTION_TEXT,
    ])


def sort_documents(items, field="name", descending=False):
    if any("position" in x for x in items):
        return sorted(items, key=lambda x: (x.get("position", 10**9), str(x.get(field, ""))))
    return sorted(items, key=lambda x: str(x.get(field, "")), reverse=descending)


async def get_years(category_key):
    items = await years_col.find({"category_key": category_key}).to_list(length=None)
    if any("position" in x for x in items):
        return sort_documents(items, "year")
    return sorted(items, key=lambda x: str(x.get("year", "")), reverse=True)


async def get_movies(year_id):
    items = await movies_col.find({"year_id": year_id}).to_list(length=None)
    return sort_documents(items, "name")


async def get_request_buttons():
    items = await request_buttons_col.find({}).to_list(length=None)
    return sort_documents(items, "name")


async def get_layout_columns(layout_key, default):
    doc = await settings_col.find_one({"_id": layout_key})
    return max(1, min(5, int(doc.get("columns", default)))) if doc else default


async def set_layout_columns(layout_key, columns):
    await settings_col.update_one({"_id": layout_key}, {"$set": {"columns": columns}}, upsert=True)


async def reorder_items(collection, items):
    for index, item in enumerate(items):
        await collection.update_one({"_id": item["_id"]}, {"$set": {"position": index}})


async def next_position(collection, query=None):
    items = await collection.find(query or {}).to_list(length=None)
    return len(items)


def item_label(item):
    return str(item.get("name", item.get("year", "Unnamed")))


async def current_items(data):
    kind = data.get("manage_type") or data.get("layout_type")
    if kind == "movie":
        return await get_movies(data["current_year_id"])
    if kind == "request":
        return await get_request_buttons()
    if kind == "year":
        return await get_years(data["current_category_key"])
    return []


def collection_for(kind):
    return {"movie": movies_col, "request": request_buttons_col, "year": years_col}[kind]


def layout_key_for(kind, data):
    if kind == "movie":
        return f"movie_layout:{data['current_year_id']}"
    if kind == "year":
        return f"year_layout:{data['current_category_key']}"
    return "request_layout"

# ============================================================
# MENU DISPLAY
# ============================================================
async def show_category(message, category, state):
    years = await get_years(category["key"])
    columns = await get_layout_columns(f"year_layout:{category['key']}", YEAR_MENU_COLUMNS)
    await state.update_data(current_category_key=category["key"], current_year_id=None, current_view="years")
    footer = [ADD_YEAR_TEXT, LAYOUT_SETUP_TEXT] if is_admin(message.from_user.id) else []
    footer.append(BACK_MAIN_TEXT)
    await message.answer("Select Year", reply_markup=make_keyboard([x["year"] for x in years], columns, footer))


async def show_movies(message, category_key, year_doc, state):
    year_id = str(year_doc["_id"])
    movies = await get_movies(year_id)
    columns = await get_layout_columns(f"movie_layout:{year_id}", MOVIE_MENU_COLUMNS)
    await state.update_data(current_category_key=category_key, current_year_id=year_id, current_view="movies")
    footer = [ADD_MOVIE_TEXT, MANAGE_BUTTONS_TEXT, LAYOUT_SETUP_TEXT] if is_admin(message.from_user.id) else []
    footer.append(BACK_YEARS_TEXT)
    await message.answer(f"📂 {year_doc['year']}", reply_markup=make_keyboard([x["name"] for x in movies], columns, footer))


async def show_request_menu(message, state):
    buttons = await get_request_buttons()
    columns = await get_layout_columns("request_layout", 2)
    footer = [ADD_REQUEST_BUTTON_TEXT, MANAGE_BUTTONS_TEXT, LAYOUT_SETUP_TEXT] if is_admin(message.from_user.id) else []
    footer.append(BACK_MAIN_TEXT)
    await state.update_data(current_view="request", current_category_key=None, current_year_id=None)
    await message.answer(REQUEST_MENU_TEXT, reply_markup=make_keyboard([x["name"] for x in buttons], columns, footer))


async def refresh_menu(message, state):
    data = await state.get_data()
    view = data.get("current_view")
    if view == "request":
        await show_request_menu(message, state)
    elif view == "movies" and data.get("current_year_id"):
        year_doc = await years_col.find_one({"_id": ObjectId(data["current_year_id"])})
        if year_doc:
            await show_movies(message, data["current_category_key"], year_doc, state)
        else:
            await message.answer("Main Menu", reply_markup=main_menu())
    elif view == "years" and data.get("current_category_key"):
        category = next((x for x in MAIN_BUTTONS if x["key"] == data["current_category_key"]), None)
        if category:
            await show_category(message, category, state)
        else:
            await message.answer("Main Menu", reply_markup=main_menu())
    else:
        await message.answer("Main Menu", reply_markup=main_menu())

# ============================================================
# LAYOUT EDITOR: SELECT AN ITEM, THEN SELECT A COORDINATE SLOT
# ============================================================
def coordinate_label(index, columns):
    row, col = divmod(index, columns)
    return f"➡️({row},{col})⬅️"


async def show_layout_item_picker(message, state):
    data = await state.get_data()
    kind = data["layout_type"]
    items = await current_items({**data, "manage_type": kind})
    columns = await get_layout_columns(layout_key_for(kind, data),
                                       YEAR_MENU_COLUMNS if kind == "year" else MOVIE_MENU_COLUMNS if kind == "movie" else 2)
    labels = [f"{('✔️ ' if str(x['_id']) == data.get('layout_selected_id') else '')}{item_label(x)}" for x in items]
    await state.set_state(AdminFlow.layout_select_item)
    await message.answer(
        "Layout Setup: Select the button you want to move. Then choose a position.",
        reply_markup=make_keyboard(labels, columns, [BACK_LAYOUT_TEXT]),
    )


async def show_layout_positions(message, state):
    data = await state.get_data()
    kind = data["layout_type"]
    items = await current_items({**data, "manage_type": kind})
    columns = await get_layout_columns(layout_key_for(kind, data),
                                       YEAR_MENU_COLUMNS if kind == "year" else MOVIE_MENU_COLUMNS if kind == "movie" else 2)
    # Include one extra insertion slot at the end.
    labels = [coordinate_label(i, columns) for i in range(len(items) + 1)]
    await state.set_state(AdminFlow.layout_select_position)
    await message.answer(
        f"Selected: {data.get('layout_selected_name', 'Button')}\nChoose its new position:",
        reply_markup=make_keyboard(labels, columns, [BACK_LAYOUT_TEXT]),
    )


async def begin_layout(message, state, kind):
    if not is_admin(message.from_user.id):
        await message.answer("Admin only.")
        return
    data = await state.get_data()
    await state.update_data(layout_type=kind, layout_selected_id=None, layout_selected_name=None)
    items = await current_items({**data, "manage_type": kind})
    if not items:
        await message.answer("No buttons found for this layout.")
        return
    await show_layout_item_picker(message, state)


@dp.message(AdminFlow.layout_select_item)
async def layout_item_selected(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == BACK_LAYOUT_TEXT:
        await state.clear()
        await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
        await refresh_menu(message, state)
        return
    items = await current_items({**data, "manage_type": data["layout_type"]})
    selected = next((x for x in items if item_label(x) == text or f"✔️ {item_label(x)}" == text), None)
    if not selected:
        await message.answer("Select a button from the list.")
        return
    await state.update_data(layout_selected_id=str(selected["_id"]), layout_selected_name=item_label(selected))
    await show_layout_positions(message, state)


@dp.message(AdminFlow.layout_select_position)
async def layout_position_selected(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == BACK_LAYOUT_TEXT:
        await show_layout_item_picker(message, state)
        return
    kind = data["layout_type"]
    items = await current_items({**data, "manage_type": kind})
    columns = await get_layout_columns(layout_key_for(kind, data),
                                       YEAR_MENU_COLUMNS if kind == "year" else MOVIE_MENU_COLUMNS if kind == "movie" else 2)
    valid_slots = {coordinate_label(i, columns): i for i in range(len(items) + 1)}
    if text not in valid_slots:
        await message.answer("Choose one of the position buttons.")
        return
    selected_id = data.get("layout_selected_id")
    old_index = next((i for i, x in enumerate(items) if str(x["_id"]) == selected_id), None)
    if old_index is None:
        await message.answer("Selected button was not found.")
        await show_layout_item_picker(message, state)
        return
    selected = items.pop(old_index)
    target = min(valid_slots[text], len(items))
    items.insert(target, selected)
    await reorder_items(collection_for(kind), items)
    await state.update_data(layout_selected_id=None, layout_selected_name=None)
    await message.answer(f"Moved to position {target + 1}.")
    await show_layout_item_picker(message, state)

# ============================================================
# CONTENT COLLECTION AND EDITING
# ============================================================
async def start_content_collection(message, state, mode, **extra):
    await state.update_data(collected_messages=[], collect_mode=mode, **extra)
    await state.set_state(AdminFlow.collecting_content)
    await message.answer("Send photos, files, videos, or text. Press Save Message when finished.", reply_markup=collect_menu())


async def show_edit_item_picker(message, state):
    data = await state.get_data()
    kind = data["manage_type"]
    items = await current_items(data)
    if not items:
        await message.answer("No buttons found.")
        await state.set_state(AdminFlow.managing_item)
        return
    await state.set_state(AdminFlow.edit_select_item)
    await message.answer(
        "Select the movie or button whose messages you want to edit:",
        reply_markup=make_keyboard([item_label(x) for x in items], 1, [BACK_ACTION_TEXT]),
    )


@dp.message(AdminFlow.edit_select_item)
async def edit_item_selected(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == BACK_ACTION_TEXT:
        await state.set_state(AdminFlow.managing_item)
        await message.answer("Button options:", reply_markup=action_menu())
        return
    items = await current_items(data)
    selected = next((x for x in items if item_label(x) == text), None)
    if not selected:
        await message.answer("Select an item from the list.")
        return
    await state.update_data(manage_item_id=str(selected["_id"]), manage_item_name=item_label(selected))
    await show_saved_messages(message, state, selected)


async def show_saved_messages(message, state, item):
    messages = item.get("messages", [])
    await message.answer(f"Saved messages for: {item_label(item)}\nTotal: {len(messages)}")
    if not messages:
        await message.answer("No saved messages.")
    for number, entry in enumerate(messages, start=1):
        await message.answer(f"Message {number}:")
        try:
            await bot.copy_message(chat_id=message.chat.id, from_chat_id=entry["chat_id"], message_id=entry["message_id"])
        except Exception:
            await message.answer(f"Message {number} could not be displayed.")
    await state.set_state(AdminFlow.edit_message_menu)
    await message.answer(
        "Choose Add Message to append new content, Delete Message to remove a numbered item, or Back.",
        reply_markup=make_keyboard([ADD_MESSAGE_TEXT, DELETE_MESSAGE_TEXT, BACK_ACTION_TEXT]),
    )


async def save_new_content(message, state, data, items):
    mode = data.get("collect_mode")
    if mode == "add_movie":
        year_id = data["year_id"]
        position = await next_position(movies_col, {"year_id": year_id})
        await movies_col.insert_one({"category_key": data["category_key"], "year_id": year_id, "name": data["movie_name"], "messages": items, "position": position, "created_by": message.from_user.id})
        await state.clear()
        await state.update_data(current_category_key=data["category_key"], current_year_id=year_id, current_view="movies")
        await message.answer(f"Movie saved: {data['movie_name']}\n{len(items)} messages saved.")
        await refresh_menu(message, state)
    elif mode == "add_request":
        position = await next_position(request_buttons_col)
        await request_buttons_col.insert_one({"name": data["request_button_name"], "messages": items, "position": position, "created_by": message.from_user.id})
        await state.clear()
        await state.update_data(current_view="request")
        await message.answer(f"Button added: {data['request_button_name']}\n{len(items)} messages saved.")
        await show_request_menu(message, state)
    elif mode == "append_existing":
        collection = collection_for(data["manage_type"])
        existing = await collection.find_one({"_id": ObjectId(data["manage_item_id"])})
        old_messages = existing.get("messages", []) if existing else []
        await collection.update_one({"_id": ObjectId(data["manage_item_id"])}, {"$set": {"messages": old_messages + items}})
        await state.clear()
        await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
        await message.answer(f"{len(items)} message(s) added.")
        await refresh_menu(message, state)


@dp.message(AdminFlow.collecting_content, F.text == SAVE_TEXT)
async def save_collected_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    items = data.get("collected_messages", [])
    if not items:
        await message.answer("Send at least one message before saving.")
        return
    await save_new_content(message, state, data, items)


@dp.message(AdminFlow.collecting_content, F.text == CANCEL_TEXT)
async def cancel_content_collection(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
    await message.answer("Operation cancelled.")
    await refresh_menu(message, state)


@dp.message(AdminFlow.collecting_content)
async def collect_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    items = data.get("collected_messages", [])
    items.append({"message_id": message.message_id, "chat_id": message.chat.id})
    await state.update_data(collected_messages=items)

# ============================================================
# BUTTON MANAGEMENT
# ============================================================
async def start_manage(message, state, kind):
    if not is_admin(message.from_user.id):
        await message.answer("Admin only.")
        return
    data = await state.get_data()
    await state.update_data(manage_type=kind)
    items = await current_items({**data, "manage_type": kind})
    if not items:
        await message.answer("No buttons found.")
        return
    await state.set_state(AdminFlow.selecting_manage_item)
    await message.answer("Select a button:", reply_markup=make_keyboard([item_label(x) for x in items], 1, [CANCEL_TEXT]))


@dp.message(AdminFlow.selecting_manage_item)
async def select_manage_item(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == CANCEL_TEXT:
        await state.clear()
        await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
        await refresh_menu(message, state)
        return
    items = await current_items(data)
    selected = next((x for x in items if item_label(x) == text), None)
    if not selected:
        await message.answer("Button not found. Select again.")
        return
    await state.update_data(manage_item_id=str(selected["_id"]), manage_item_name=item_label(selected))
    await state.set_state(AdminFlow.managing_item)
    await message.answer(f"Selected: {item_label(selected)}", reply_markup=action_menu())


async def move_managed_item(message, state, direction):
    data = await state.get_data()
    items = await current_items(data)
    index = next((i for i, x in enumerate(items) if str(x["_id"]) == data.get("manage_item_id")), None)
    if index is None:
        await message.answer("Button not found.")
        return
    if direction == "up" and index > 0:
        items[index - 1], items[index] = items[index], items[index - 1]
    elif direction == "down" and index < len(items) - 1:
        items[index + 1], items[index] = items[index], items[index + 1]
    elif direction == "top":
        items.insert(0, items.pop(index))
    elif direction == "bottom":
        items.append(items.pop(index))
    await reorder_items(collection_for(data["manage_type"]), items)
    await message.answer("Button order updated.", reply_markup=action_menu())


@dp.message(AdminFlow.managing_item)
async def manage_selected_item(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == BACK_ACTION_TEXT:
        await state.clear()
        await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
        await refresh_menu(message, state)
        return
    item = await collection_for(data["manage_type"]).find_one({"_id": ObjectId(data["manage_item_id"])})
    if not item:
        await message.answer("Button not found.")
        return
    if text == DELETE_BUTTON_TEXT:
        await state.update_data(delete_confirmation=True)
        await message.answer(f"Delete '{item_label(item)}'?", reply_markup=make_keyboard([CONFIRM_DELETE_TEXT, BACK_ACTION_TEXT]))
    elif text == CONFIRM_DELETE_TEXT:
        await collection_for(data["manage_type"]).delete_one({"_id": ObjectId(data["manage_item_id"])})
        await state.clear()
        await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
        await message.answer("Button deleted.")
        await refresh_menu(message, state)
    elif text == RENAME_BUTTON_TEXT:
        await state.set_state(AdminFlow.waiting_rename)
        await message.answer("Send the new button name:", reply_markup=cancel_menu())
    elif text == EDIT_MESSAGE_TEXT:
        await show_edit_item_picker(message, state)
    elif text == DELETE_MESSAGE_TEXT:
        await show_saved_messages(message, state, item)
    elif text == MOVE_UP_TEXT:
        await move_managed_item(message, state, "up")
    elif text == MOVE_DOWN_TEXT:
        await move_managed_item(message, state, "down")
    elif text == MOVE_TOP_TEXT:
        await move_managed_item(message, state, "top")
    elif text == MOVE_BOTTOM_TEXT:
        await move_managed_item(message, state, "bottom")
    elif text == MOVE_POSITION_TEXT:
        await state.set_state(AdminFlow.waiting_position)
        await message.answer("Send the new position number, starting from 1:", reply_markup=cancel_menu())
    else:
        await message.answer("Choose an action.", reply_markup=action_menu())


@dp.message(AdminFlow.edit_message_menu)
async def edit_message_menu(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == BACK_ACTION_TEXT:
        await state.set_state(AdminFlow.managing_item)
        await message.answer("Button options:", reply_markup=action_menu())
    elif text == ADD_MESSAGE_TEXT:
        await start_content_collection(message, state, "append_existing", manage_type=data["manage_type"], manage_item_id=data["manage_item_id"], current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
    elif text == DELETE_MESSAGE_TEXT:
        await state.set_state(AdminFlow.waiting_message_number)
        await message.answer("Send the message number to delete:", reply_markup=cancel_menu())
    else:
        await message.answer("Choose Add Message, Delete Message, or Back.")


@dp.message(AdminFlow.waiting_message_number)
async def delete_message_number(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == CANCEL_TEXT:
        item = await collection_for(data["manage_type"]).find_one({"_id": ObjectId(data["manage_item_id"])})
        if item:
            await show_saved_messages(message, state, item)
        return
    if not text.isdigit():
        await message.answer("Send a valid message number.")
        return
    collection = collection_for(data["manage_type"])
    item = await collection.find_one({"_id": ObjectId(data["manage_item_id"])})
    messages = item.get("messages", []) if item else []
    number = int(text)
    if number < 1 or number > len(messages):
        await message.answer(f"Enter a number from 1 to {len(messages)}.")
        return
    removed = messages.pop(number - 1)
    await collection.update_one({"_id": ObjectId(data["manage_item_id"])}, {"$set": {"messages": messages}})
    await message.answer(f"Message {number} deleted.")
    updated = await collection.find_one({"_id": ObjectId(data["manage_item_id"])})
    await show_saved_messages(message, state, updated)


@dp.message(AdminFlow.waiting_rename)
async def rename_selected_button(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    new_name = (message.text or "").strip()
    data = await state.get_data()
    if new_name == CANCEL_TEXT:
        await state.set_state(AdminFlow.managing_item)
        await message.answer("Rename cancelled.", reply_markup=action_menu())
        return
    if not new_name or len(new_name) > 60:
        await message.answer("Send a valid name.")
        return
    collection = collection_for(data["manage_type"])
    if data["manage_type"] == "request":
        duplicate = await collection.find_one({"name": new_name, "_id": {"$ne": ObjectId(data["manage_item_id"])}})
        if duplicate:
            await message.answer("This button name already exists.")
            return
    await collection.update_one({"_id": ObjectId(data["manage_item_id"])}, {"$set": {"name": new_name}})
    await state.clear()
    await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
    await message.answer("Button renamed.")
    await refresh_menu(message, state)


@dp.message(AdminFlow.waiting_position)
async def move_to_position(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == CANCEL_TEXT:
        await state.set_state(AdminFlow.managing_item)
        await message.answer("Position change cancelled.", reply_markup=action_menu())
        return
    if not text.isdigit():
        await message.answer("Send a valid position number.")
        return
    items = await current_items(data)
    index = next((i for i, x in enumerate(items) if str(x["_id"]) == data["manage_item_id"]), None)
    if index is None:
        await message.answer("Button not found.")
        return
    selected = items.pop(index)
    target = max(1, min(int(text), len(items) + 1))
    items.insert(target - 1, selected)
    await reorder_items(collection_for(data["manage_type"]), items)
    await state.set_state(AdminFlow.managing_item)
    await message.answer(f"Moved to position {target}.", reply_markup=action_menu())

# ============================================================
# YEAR / MOVIE / REQUEST ADD FLOWS
# ============================================================
@dp.message(AdminFlow.waiting_year)
async def receive_year(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    value = (message.text or "").strip()
    data = await state.get_data()
    if value == CANCEL_TEXT:
        await state.clear(); await state.update_data(current_view="years", current_category_key=data.get("category_key")); await refresh_menu(message, state); return
    if not value or len(value) > 20:
        await message.answer("Send a valid year, for example 2026."); return
    category_key = data.get("category_key")
    if await years_col.find_one({"category_key": category_key, "year": value}):
        await message.answer("This year already exists. Send another year."); return
    position = await next_position(years_col, {"category_key": category_key})
    await years_col.insert_one({"category_key": category_key, "year": value, "position": position})
    await state.clear(); await state.update_data(current_view="years", current_category_key=category_key)
    await message.answer(f"Year added: {value}")
    await refresh_menu(message, state)


@dp.message(AdminFlow.waiting_movie_name)
async def receive_movie_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    name = (message.text or "").strip()
    if not name or name in (SAVE_TEXT, CANCEL_TEXT, ADD_MOVIE_TEXT):
        await message.answer("Send a valid movie name."); return
    data = await state.get_data()
    await start_content_collection(message, state, "add_movie", movie_name=name, category_key=data["category_key"], year_id=data["year_id"], current_view="movies", current_category_key=data["category_key"], current_year_id=data["year_id"])


@dp.message(AdminFlow.waiting_request_button_name)
async def receive_request_button_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    name = (message.text or "").strip()
    if not name or name in (SAVE_TEXT, CANCEL_TEXT, ADD_REQUEST_BUTTON_TEXT):
        await message.answer("Send a valid button name."); return
    if await request_buttons_col.find_one({"name": name}):
        await message.answer("This button name already exists. Send another name."); return
    await start_content_collection(message, state, "add_request", request_button_name=name, current_view="request")

# ============================================================
# LAYOUT COLUMN SETTINGS
# ============================================================
@dp.message(AdminFlow.waiting_columns)
async def receive_columns(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear(); return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == CANCEL_TEXT:
        await state.clear(); await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id")); await refresh_menu(message, state); return
    if text not in COLUMN_OPTIONS:
        await message.answer("Choose a layout from the keyboard."); return
    columns = COLUMN_OPTIONS.index(text) + 1
    kind = data["layout_type"]
    await set_layout_columns(layout_key_for(kind, data), columns)
    await state.clear(); await state.update_data(current_view=data.get("current_view"), current_category_key=data.get("current_category_key"), current_year_id=data.get("current_year_id"))
    await message.answer(f"Layout updated: {columns} button(s) per row.")
    await refresh_menu(message, state)

# ============================================================
# MAIN MENU AND NAVIGATION
# ============================================================
@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🎬 Welcome!\n\nChoose an option from the Main Menu.", reply_markup=main_menu())


@dp.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.", reply_markup=main_menu())


@dp.message(Command("id"))
async def show_id(message: Message):
    await message.answer(f"Your Telegram ID: <code>{message.from_user.id}</code>", parse_mode=ParseMode.HTML)


async def handle_main_menu(message, state):
    chosen = next((x for x in MAIN_BUTTONS if x["text"] == message.text), None)
    if not chosen:
        return False
    await state.clear()
    if chosen["type"] == "request":
        await show_request_menu(message, state)
    else:
        await show_category(message, chosen, state)
    return True


@dp.message(F.text)
async def text_navigation(message: Message, state: FSMContext):
    if await state.get_state() is not None:
        return
    text = (message.text or "").strip()
    if await handle_main_menu(message, state):
        return
    data = await state.get_data()
    view = data.get("current_view")
    category_key = data.get("current_category_key")

    if text == BACK_MAIN_TEXT:
        await state.clear(); await message.answer("Main Menu", reply_markup=main_menu()); return
    if text == BACK_YEARS_TEXT and view == "movies" and category_key:
        category = next((x for x in MAIN_BUTTONS if x["key"] == category_key), None)
        if category: await show_category(message, category, state)
        return

    if text == ADD_YEAR_TEXT and view == "years" and is_admin(message.from_user.id):
        await state.update_data(category_key=category_key)
        await state.set_state(AdminFlow.waiting_year)
        await message.answer("Send the year. Example: 2026", reply_markup=cancel_menu()); return

    if text == ADD_MOVIE_TEXT and view == "movies" and is_admin(message.from_user.id):
        await state.update_data(category_key=category_key, year_id=data.get("current_year_id"))
        await state.set_state(AdminFlow.waiting_movie_name)
        await message.answer("Send the movie name:", reply_markup=cancel_menu()); return

    if text == ADD_REQUEST_BUTTON_TEXT and view == "request" and is_admin(message.from_user.id):
        await state.set_state(AdminFlow.waiting_request_button_name)
        await message.answer("Send the new button name:", reply_markup=cancel_menu()); return

    if text == MANAGE_BUTTONS_TEXT and view == "movies":
        await start_manage(message, state, "movie"); return
    if text == MANAGE_BUTTONS_TEXT and view == "request":
        await start_manage(message, state, "request"); return

    if text == LAYOUT_SETUP_TEXT and view == "movies":
        await begin_layout(message, state, "movie"); return
    if text == LAYOUT_SETUP_TEXT and view == "request":
        await begin_layout(message, state, "request"); return
    if text == LAYOUT_SETUP_TEXT and view == "years":
        await begin_layout(message, state, "year"); return

    if view == "years" and category_key:
        year_doc = await years_col.find_one({"category_key": category_key, "year": text})
        if year_doc:
            await show_movies(message, category_key, year_doc, state); return

    if view == "movies" and data.get("current_year_id"):
        movie = await movies_col.find_one({"year_id": data["current_year_id"], "name": text})
        if movie:
            saved = movie.get("messages", [])
            if not saved:
                await message.answer("No messages are saved for this movie yet."); return
            for entry in saved:
                try:
                    await bot.copy_message(chat_id=message.chat.id, from_chat_id=entry["chat_id"], message_id=entry["message_id"])
                except Exception:
                    await message.answer("One message from this movie could not be sent.")
            return

    if view == "request":
        button = await request_buttons_col.find_one({"name": text})
        if button:
            saved = button.get("messages", [])
            if not saved:
                await message.answer("No messages are saved for this button yet."); return
            for entry in saved:
                try:
                    await bot.copy_message(chat_id=message.chat.id, from_chat_id=entry["chat_id"], message_id=entry["message_id"])
                except Exception:
                    await message.answer("One message could not be sent.")
            return

# ============================================================
# BOT STARTUP
# ============================================================
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    print("Movie Button Bot is running...")
    try:
        await dp.start_polling(bot)
    finally:
        mongo.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
