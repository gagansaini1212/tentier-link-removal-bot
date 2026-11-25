import asyncio
import logging
import os
import re
from pathlib import Path

from telegram import (
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageEntity,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
AUTO_CLEAN_DELAY_SECONDS = 300  # 5 minutes

# Matches URLs, t.me / wa.me / bit.ly links, and domain.tld patterns
LINK_REGEX = re.compile(
    r"(?i)(?:https?://|www\.)\S+"
    r"|(?<![@\w])(?:t\.me|telegram\.me|telegram\.dog|wa\.me|bit\.ly|tinyurl\.com|goo\.gl)/\S+"
    r"|(?<![@\w])[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.(?:com|net|org|io|co|in|info|biz|xyz|me|gg|ly|app|dev|ai|shop|site|online|club|vip|top|link)(?:/\S*)?(?=\s|$|[.,!?;:)])"
)

LINK_ENTITY_TYPES = {MessageEntity.URL, MessageEntity.TEXT_LINK}


def _read_env_value(key_name: str) -> str:
    """Read a config value from environment variables or local .env file."""
    val = os.environ.get(key_name, "").strip()
    if val:
        return val

    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == key_name:
                return value.strip().strip('"').strip("'")
    return ""


def load_token() -> str:
    token = _read_env_value("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. Add it to .env or export it in your shell."
        )
    return token


def load_admin_ids() -> set[int]:
    """Parse comma-separated Telegram numeric user IDs from ADMIN_USER_IDS."""
    raw = _read_env_value("ADMIN_USER_IDS")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS: set[int] = load_admin_ids()


def contains_link(message: Message) -> bool:
    """Detect URLs, hidden text links, and domain links in text or media captions."""
    entities = list(message.entities or ()) + list(message.caption_entities or ())
    if any(ent.type in LINK_ENTITY_TYPES for ent in entities):
        return True

    for content in (message.text, message.caption):
        if content and LINK_REGEX.search(content):
            return True

    return False


async def is_user_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if sender is a group admin, anonymous admin, or in ADMIN_USER_IDS."""
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if not chat:
        return False

    if msg and msg.is_automatic_forward:
        return True

    if chat.type in ("group", "supergroup") and msg and msg.sender_chat:
        if msg.sender_chat.id == chat.id:
            return True

    if user and user.id in ADMIN_IDS:
        return True

    if chat.type in ("group", "supergroup") and user:
        try:
            member = await context.bot.get_chat_member(chat.id, user.id)
            return member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER)
        except Exception as exc:
            logger.warning("Failed to check member status in %s: %s", chat.id, exc)

    return False


async def bot_can_delete(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Return True if the bot is a group admin with Delete Messages permission."""
    try:
        member = await context.bot.get_chat_member(chat_id, context.bot.id)
        if member.status == ChatMember.OWNER:
            return True
        if member.status == ChatMember.ADMINISTRATOR:
            return bool(getattr(member, "can_delete_messages", False))
        return False
    except Exception as exc:
        logger.warning("Failed to check bot permissions in %s: %s", chat_id, exc)
        return False


async def _delete_after_delay(
    bot, chat_id: int, message_id: int, delay: int = AUTO_CLEAN_DELAY_SECONDS
) -> None:
    try:
        await asyncio.sleep(delay)
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        logger.debug("Auto-clean skipped for %s in %s: %s", message_id, chat_id, exc)


def schedule_auto_clean(
    bot, chat_id: int, message_id: int, delay: int = AUTO_CLEAN_DELAY_SECONDS
) -> None:
    """Schedule deletion of a message after delay seconds (default: 5 minutes)."""
    asyncio.create_task(_delete_after_delay(bot, chat_id, message_id, delay))


async def handle_my_chat_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Check admin & delete-messages permission when added or updated in a group."""
    chat_member = update.my_chat_member
    if not chat_member:
        return

    chat = chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = chat_member.old_chat_member.status
    new_member = chat_member.new_chat_member
    new_status = new_member.status

    if old_status in (ChatMember.LEFT, ChatMember.BANNED) and new_status == ChatMember.MEMBER:
        sent = await context.bot.send_message(
            chat_id=chat.id,
            text=(
                "Admin access required: Please promote me to Group Admin with "
                "'Delete Messages' permission so I can remove non-admin links."
            ),
        )
        schedule_auto_clean(context.bot, chat.id, sent.message_id)
    elif new_status == ChatMember.ADMINISTRATOR:
        can_del = bool(getattr(new_member, "can_delete_messages", False))
        if not can_del:
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "Please enable the 'Delete Messages' admin permission for me "
                    "so I can remove links posted by non-admin users."
                ),
            )
            schedule_auto_clean(context.bot, chat.id, sent.message_id)
        elif old_status != ChatMember.ADMINISTRATOR:
            sent = await context.bot.send_message(
                chat_id=chat.id,
                text="Anti-Link protection is active! Links posted by non-admins will be removed immediately.",
            )
            schedule_auto_clean(context.bot, chat.id, sent.message_id)


async def clean_welcome_service_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Auto-clean Telegram join/welcome service messages after 5 minutes."""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg or chat.type not in ("group", "supergroup"):
        return

    if not await bot_can_delete(chat.id, context):
        return

    schedule_auto_clean(context.bot, chat.id, msg.message_id)
    logger.info(
        "Scheduled 5-minute auto-clean for welcome message %s in chat %s",
        msg.message_id,
        chat.id,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or not update.message:
        return

    if chat.type in ("group", "supergroup"):
        if not await bot_can_delete(chat.id, context):
            await update.message.reply_text(
                "Please promote me to Group Admin with 'Delete Messages' permission."
            )
            return
        if await is_user_admin(update, context):
            await update.message.reply_text(
                "Anti-Link protection is active in this group. "
                "Any link posted by non-admin users will be deleted immediately."
            )
        return

    bot_username = context.bot.username or ""
    if bot_username:
        add_url = f"https://t.me/{bot_username}?startgroup=true&admin=delete_messages"
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Add to Group as Admin", url=add_url)]]
        )
    else:
        keyboard = None

    await update.message.reply_text(
        "Anti-Link Moderator Bot\n\n"
        "Add me to a group as Admin with 'Delete Messages' permission. "
        "I will automatically delete any links posted or edited by non-admin users.",
        reply_markup=keyboard,
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    if not await is_user_admin(update, context):
        return

    can_del = await bot_can_delete(chat.id, context)
    state = "ACTIVE (can delete messages)" if can_del else "INACTIVE (needs Admin + Delete Messages)"
    await update.message.reply_text(f"Anti-Link status: {state}")


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete messages (and edited messages) containing links from non-admins."""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg or chat.type not in ("group", "supergroup"):
        return

    if not contains_link(msg):
        return

    if await is_user_admin(update, context):
        return

    try:
        await msg.delete()
        user = update.effective_user
        logger.info(
            "Deleted link message %s from user %s in chat %s",
            msg.message_id,
            user.id if user else "unknown",
            chat.id,
        )
    except Exception as exc:
        logger.warning(
            "Could not delete message %s in chat %s: %s",
            msg.message_id,
            chat.id,
            exc,
        )


def main() -> None:
    token = load_token()
    app = ApplicationBuilder().token(token).build()
    app.add_handler(
        ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS,
            clean_welcome_service_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & ~filters.COMMAND,
            moderate_message,
        )
    )

    logger.info("Anti-Link bot is running (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
