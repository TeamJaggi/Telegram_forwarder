import asyncio
import json
import os
import re
import logging
import ssl # Import ssl module
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

import aiohttp
from aiohttp import web
# Removed requests as aiohttp.ClientSession is used consistently

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class BotConfig:
    bot_token: str
    webhook_url: str = ""
    webhook_port: int = 8443
    admin_users: List[int] = None
    source_channels: List[str] = None
    target_channel: str = ""
    replacements: Dict = None
    forwarding_enabled: bool = False
    
    def __post_init__(self):
        if self.admin_users is None:
            self.admin_users = []
        if self.source_channels is None:
            self.source_channels = []
        if self.replacements is None:
            self.replacements = {
                "links": {},
                "words": {},
                "sentences": {}
            }

class TelegramForwarderBot:
    def __init__(self, bot_token: str, webhook_url: str = "", webhook_port: int = 8443):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        
        self.config_file = "bot_config.json"
        self.config = self.load_config()
        # Ensure config matches constructor arguments, prioritizing passed values
        self.config.bot_token = bot_token
        self.config.webhook_url = webhook_url
        self.config.webhook_port = webhook_port
        
        self.app = web.Application()
        self.setup_routes()
        
    def load_config(self) -> BotConfig:
        """Load configuration from file, handling missing fields gracefully."""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Create BotConfig from loaded data, providing defaults for potentially missing keys
                    return BotConfig(
                        bot_token=data.get('bot_token', ""),
                        webhook_url=data.get('webhook_url', ""),
                        webhook_port=data.get('webhook_port', 8443),
                        admin_users=data.get('admin_users', []),
                        source_channels=data.get('source_channels', []),
                        target_channel=data.get('target_channel', ""),
                        replacements=data.get('replacements', {"links": {}, "words": {}, "sentences": {}}),
                        forwarding_enabled=data.get('forwarding_enabled', False)
                    )
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON from config file '{self.config_file}': {e}. Creating default config.")
            except IOError as e:
                logger.error(f"Error reading config file '{self.config_file}': {e}. Creating default config.")
            except Exception as e:
                logger.error(f"An unexpected error occurred loading config: {e}. Creating default config.")
        
        logger.info("No existing config file or error loading it. Creating a new default configuration.")
        return BotConfig(bot_token="") # Return a default config if loading fails or file doesn't exist
    
    def save_config(self):
        """Save configuration to file."""
        try:
            config_dict = {
                'bot_token': self.config.bot_token,
                'webhook_url': self.config.webhook_url,
                'webhook_port': self.config.webhook_port,
                'admin_users': self.config.admin_users,
                'source_channels': self.config.source_channels,
                'target_channel': self.config.target_channel,
                'replacements': self.config.replacements,
                'forwarding_enabled': self.config.forwarding_enabled
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            logger.info("Configuration saved successfully.")
        except IOError as e:
            logger.error(f"Error writing config file '{self.config_file}': {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred saving config: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return user_id in self.config.admin_users
    
    def apply_replacements(self, text: str) -> str:
        """Apply all text replacements"""
        if not text:
            return text
        
        modified_text = text
        
        try:
            # Apply link replacements
            for old_link, new_link in self.config.replacements["links"].items():
                modified_text = modified_text.replace(old_link, new_link)
            
            # Apply word replacements (case-insensitive)
            # Sort words by length descending to prevent partial replacements of longer words
            # if a shorter word is a substring (e.g., 'car' before 'carpet')
            sorted_words = sorted(self.config.replacements["words"].items(), key=lambda item: len(item[0]), reverse=True)
            for old_word, new_word in sorted_words:
                # Use \b for whole word matching to avoid replacing parts of words
                # re.escape is crucial for words that might contain regex special characters
                modified_text = re.sub(r'\b' + re.escape(old_word) + r'\b', new_word, modified_text, flags=re.IGNORECASE)
            
            # Apply sentence replacements (case-sensitive as typically desired for sentences)
            # Sort sentences by length descending for similar reasons as words
            sorted_sentences = sorted(self.config.replacements["sentences"].items(), key=lambda item: len(item[0]), reverse=True)
            for old_sentence, new_sentence in sorted_sentences:
                modified_text = modified_text.replace(old_sentence, new_sentence)
        except Exception as e:
            logger.error(f"Error applying replacements: {e}. Original text returned.")
            return text # Return original text on error
            
        return modified_text
    
    async def _send_api_request(self, method: str, payload: Dict):
        """Helper to send requests to Telegram Bot API with error handling."""
        url = f"{self.base_url}/{method}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as response:
                    if response.status != 200:
                        logger.error(f"Telegram API request failed for {method} with status {response.status}. Payload: {payload}")
                        try:
                            error_response = await response.json()
                            logger.error(f"API Error Response: {error_response}")
                            return {"ok": False, "description": error_response.get("description", "Unknown API error")}
                        except aiohttp.ContentTypeError:
                            logger.error("API response was not JSON.")
                            return {"ok": False, "description": "API response not JSON"}
                    
                    result = await response.json()
                    if not result.get("ok"):
                        logger.error(f"Telegram API reported error for {method}: {result.get('description')}. Payload: {payload}")
                    return result
        except aiohttp.ClientError as e:
            logger.error(f"Network or client error during API request for {method}: {e}. Payload: {payload}")
            return {"ok": False, "description": f"Network/Client Error: {e}"}
        except Exception as e:
            logger.error(f"An unexpected error occurred during API request for {method}: {e}. Payload: {payload}")
            return {"ok": False, "description": f"Unexpected Error: {e}"}

    async def send_message(self, chat_id: str, text: str, reply_markup=None, parse_mode="HTML"):
        """Send message via Bot API"""
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)
        
        return await self._send_api_request("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str, text: str = None, show_alert: bool = False):
        """Answer callback query to remove loading state or show alert"""
        payload = {
            "callback_query_id": callback_query_id
        }
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = show_alert
        
        return await self._send_api_request("answerCallbackQuery", payload)
    
    async def forward_message(self, from_chat_id: str, to_chat_id: str, message_id: int):
        """Forward message via Bot API"""
        payload = {
            "chat_id": to_chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        }
        return await self._send_api_request("forwardMessage", payload)
    
    async def copy_message(self, from_chat_id: str, to_chat_id: str, message_id: int, caption: str = None):
        """Copy message via Bot API (without 'forwarded from' label)"""
        payload = {
            "chat_id": to_chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id
        }
        if caption is not None: # Use is not None to allow empty string captions
            payload["caption"] = caption
            payload["parse_mode"] = "HTML" # Ensure caption supports HTML if text does
        
        return await self._send_api_request("copyMessage", payload)
    
    async def send_photo(self, chat_id: str, photo: str, caption: str = None):
        """Send photo via Bot API"""
        payload = {
            "chat_id": chat_id,
            "photo": photo
        }
        if caption is not None:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        return await self._send_api_request("sendPhoto", payload)
    
    async def send_document(self, chat_id: str, document: str, caption: str = None):
        """Send document via Bot API"""
        payload = {
            "chat_id": chat_id,
            "document": document
        }
        if caption is not None:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        return await self._send_api_request("sendDocument", payload)
    
    async def send_video(self, chat_id: str, video: str, caption: str = None):
        """Send video via Bot API"""
        payload = {
            "chat_id": chat_id,
            "video": video
        }
        if caption is not None:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        return await self._send_api_request("sendVideo", payload)
    
    def setup_routes(self):
        """Setup webhook routes"""
        self.app.router.add_post('/webhook', self.webhook_handler)
        self.app.router.add_get('/status', self.status_handler)
    
    async def webhook_handler(self, request):
        """Handle incoming webhooks"""
        try:
            data = await request.json()
            # logger.info(f"Received webhook update: {json.dumps(data, indent=2)}") # Uncomment for debugging
            await self.process_update(data)
            return web.Response(text="OK")
        except json.JSONDecodeError:
            logger.error("Webhook received non-JSON payload.")
            return web.Response(text="Bad Request", status=400)
        except Exception as e:
            logger.error(f"Webhook processing error: {e}", exc_info=True) # exc_info for traceback
            return web.Response(text="Error", status=500)
    
    async def status_handler(self, request):
        """Status endpoint"""
        status = {
            "bot_running": True,
            "forwarding_enabled": self.config.forwarding_enabled,
            "source_channels_count": len(self.config.source_channels),
            "target_channel": self.config.target_channel if self.config.target_channel else "Not Set",
            "admin_users_count": len(self.config.admin_users),
            "active_replacements_count": sum(len(r) for r in self.config.replacements.values())
        }
        return web.json_response(status)
    
    async def process_update(self, update):
        """Process incoming update"""
        try:
            # Handle channel posts
            if "channel_post" in update:
                await self.handle_channel_post(update["channel_post"])
            
            # Handle private messages (bot commands)
            elif "message" in update:
                await self.handle_message(update["message"])
            
            # Handle callback queries (inline buttons)
            elif "callback_query" in update:
                await self.handle_callback_query(update["callback_query"])
                
        except Exception as e:
            logger.error(f"Error processing update: {e}", exc_info=True)
    
    async def handle_channel_post(self, post):
        """Handle channel post (forwarding logic)"""
        if not self.config.forwarding_enabled:
            logger.debug("Forwarding disabled, skipping channel post.")
            return
        
        if not self.config.target_channel:
            logger.warning("Target channel not set, cannot forward.")
            return
        
        channel_id = str(post["chat"]["id"])
        channel_username = post["chat"].get("username", "")
        
        # Check if this channel is in our source list
        is_source_channel = False
        for source in self.config.source_channels:
            # Normalize source channel for comparison (e.g., remove '@' if present)
            normalized_source = source.lstrip('@')
            if (str(channel_id) == normalized_source or 
                channel_username.lower() == normalized_source.lower()): # Case-insensitive for username
                is_source_channel = True
                break
        
        if not is_source_channel:
            logger.debug(f"Channel {channel_username or channel_id} is not a configured source channel.")
            return
        
        try:
            await self.forward_channel_message(post)
            logger.info(f"Forwarded message from {channel_username or channel_id} to {self.config.target_channel}")
        except Exception as e:
            logger.error(f"Error forwarding channel message from {channel_username or channel_id}: {e}", exc_info=True)
    
    async def forward_channel_message(self, post):
        """Forward channel message with replacements"""
        message_id = post["message_id"]
        from_chat_id = str(post["chat"]["id"])
        to_chat_id = self.config.target_channel
        
        original_text = post.get("text", "")
        original_caption = post.get("caption", "")
        
        # Apply replacements
        new_text = self.apply_replacements(original_text)
        new_caption = self.apply_replacements(original_caption)
        
        # Determine if text/caption was modified
        text_modified = new_text != original_text
        caption_modified = new_caption != original_caption
        
        # Determine if message can be copied with caption or text
        # If original text/caption exists AND modified, we use send_message/send_photo/etc.
        # If original text/caption doesn't exist or not modified, we use copy_message if possible
        
        if post.get("photo"):
            photo_file_id = post["photo"][-1]["file_id"]  # Get largest photo
            if caption_modified:
                await self.send_photo(to_chat_id, photo_file_id, new_caption)
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
        
        elif post.get("video"):
            video_file_id = post["video"]["file_id"]
            if caption_modified:
                await self.send_video(to_chat_id, video_file_id, new_caption)
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
        
        elif post.get("document"):
            document_file_id = post["document"]["file_id"]
            if caption_modified:
                await self.send_document(to_chat_id, document_file_id, new_caption)
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
        
        elif post.get("animation"):
            animation_file_id = post["animation"]["file_id"]
            if caption_modified:
                await self.send_document(to_chat_id, animation_file_id, new_caption) # Animation is sent as document
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
        
        elif post.get("text"): # Handle text messages (no other media)
            if text_modified:
                await self.send_message(to_chat_id, new_text)
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
        
        else: # Handle other message types that might have only a caption, or no text/caption at all (e.g., stickers, voice, etc.)
            # If there was an original caption and it was modified, use copy_message with the new caption
            # Otherwise, just copy the message as is
            if original_caption and caption_modified:
                await self.copy_message(from_chat_id, to_chat_id, message_id, new_caption)
            else:
                await self.copy_message(from_chat_id, to_chat_id, message_id)
    
    async def handle_message(self, message):
        """Handle private messages (bot commands)"""
        if "text" not in message:
            return
        
        text = message["text"].strip()
        user_id = message["from"]["id"]
        chat_id = str(message["chat"]["id"])
        
        # Commands that don't require admin (e.g., initial setup, or if you had public commands)
        if text.startswith("/start"):
            # Only allow if no admins configured yet, or if user is an admin
            if not self.config.admin_users:
                # First run setup for admin
                await self.send_message(chat_id, 
                    "Welcome! It looks like this is the first run or no admins are set. "
                    "To become the first admin, reply with your Telegram User ID."
                    "\n\n<b>How to find your User ID:</b> You can use a bot like @userinfobot to get your ID. It's a number like <code>123456789</code>."
                )
                # Store chat_id temporarily to know where to expect the ID
                self._expecting_first_admin_id = chat_id
                return
            await self.cmd_start(chat_id, user_id)
        elif self.is_admin(user_id):
            # Command routing for admins
            if text.startswith("/status"):
                await self.cmd_status(chat_id, user_id)
            elif text.startswith("/admin"):
                await self.cmd_admin(chat_id, user_id)
            elif text.startswith("/channels"):
                await self.cmd_channels(chat_id, user_id)
            elif text.startswith("/target"):
                await self.cmd_target(chat_id, user_id)
            elif text.startswith("/replacements"):
                await self.cmd_replacements(chat_id, user_id)
            elif text.startswith("/start_forwarding"):
                await self.cmd_start_forwarding(chat_id, user_id)
            elif text.startswith("/stop_forwarding"):
                await self.cmd_stop_forwarding(chat_id, user_id)
            elif text.startswith("/add_admin"):
                await self.cmd_add_admin(chat_id, user_id, text)
            elif text.startswith("/remove_admin"):
                await self.cmd_remove_admin(chat_id, user_id, text)
            elif text.startswith("/add_channel"):
                await self.cmd_add_channel(chat_id, user_id, text)
            elif text.startswith("/remove_channel"):
                await self.cmd_remove_channel(chat_id, user_id, text)
            elif text.startswith("/set_target"):
                await self.cmd_set_target(chat_id, user_id, text)
            elif text.startswith("/clear_target"):
                await self.cmd_clear_target(chat_id, user_id)
            elif text.startswith("/add_link"):
                await self.cmd_add_link(chat_id, user_id, text)
            elif text.startswith("/remove_link"):
                await self.cmd_remove_link(chat_id, user_id, text)
            elif text.startswith("/add_word"):
                await self.cmd_add_word(chat_id, user_id, text)
            elif text.startswith("/remove_word"):
                await self.cmd_remove_word(chat_id, user_id, text)
            elif text.startswith("/add_sentence"):
                await self.cmd_add_sentence(chat_id, user_id, text)
            elif text.startswith("/remove_sentence"):
                await self.cmd_remove_sentence(chat_id, user_id, text)
            elif text.startswith("/clear_replacements"):
                await self.cmd_clear_replacements(chat_id, user_id, text)
            elif text.startswith("/help"):
                await self.cmd_help(chat_id, user_id)
            else:
                # If first run and expecting admin ID
                if not self.config.admin_users and hasattr(self, '_expecting_first_admin_id') and self._expecting_first_admin_id == chat_id:
                    try:
                        potential_admin_id = int(text.strip())
                        self.config.admin_users.append(potential_admin_id)
                        self.save_config()
                        del self._expecting_first_admin_id # Clear the flag
                        await self.send_message(chat_id, 
                            f"🎉 Success! User ID <code>{potential_admin_id}</code> has been set as the first admin."
                            "\nYou can now use /start to see available commands."
                        )
                        logger.info(f"Initial admin set to {potential_admin_id}")
                    except ValueError:
                        await self.send_message(chat_id, "❌ Invalid User ID. Please send a valid number.")
                else:
                    await self.send_message(chat_id, "🤷‍♂️ Unknown command. Use /help for a list of commands.")
        else:
            await self.send_message(chat_id, "❌ You are not authorized to use this bot. Contact an admin.")
    
    async def cmd_start(self, chat_id: str, user_id: int):
        """Start command handler"""
        # Admin check already done in handle_message, this is for authorized users
        
        welcome_msg = """
🤖 <b>Telegram Auto-Forwarder Bot</b>

<b>Available Commands:</b>
📋 /status - Check bot status
👥 /admin - Admin management
📢 /channels - Manage source channels  
🎯 /target - Set target channel
🔄 /replacements - Manage text replacements
▶️ /start_forwarding - Start forwarding
⏹️ /stop_forwarding - Stop forwarding
❓ /help - Show this help

Ready to forward messages! 🚀

<b>Note:</b> This bot forwards from PUBLIC channels using Bot API - no user account needed!
        """
        await self.send_message(chat_id, welcome_msg)
    
    async def cmd_status(self, chat_id: str, user_id: int):
        """Status command handler"""
        forwarding_status = "✅ Active" if self.config.forwarding_enabled else "❌ Inactive"
        
        status_msg = f"""
📊 <b>Bot Status</b>

🤖 Bot Client: ✅ Connected
🔄 Forwarding: {forwarding_status}
📢 Source Channels: {len(self.config.source_channels)}
🎯 Target Channel: {"✅ Set" if self.config.target_channel else "❌ Not Set"}
🔧 Active Replacements: {sum(len(r) for r in self.config.replacements.values())}

<b>Webhook Mode:</b> ✅ Active
<b>Source Channels:</b>
{chr(10).join([f"• <code>{ch}</code>" for ch in self.config.source_channels]) if self.config.source_channels else "None"}
        """
        await self.send_message(chat_id, status_msg)
    
    async def cmd_admin(self, chat_id: str, user_id: int):
        """Admin command handler"""
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Add Admin", "callback_data": "add_admin_help"}, 
                 {"text": "➖ Remove Admin", "callback_data": "remove_admin_help"}],
                [{"text": "📋 List Admins", "callback_data": "list_admins"}]
            ]
        }
        await self.send_message(chat_id, "👥 <b>Admin Management</b>", keyboard)
    
    async def cmd_channels(self, chat_id: str, user_id: int):
        """Channels command handler"""
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Add Channel", "callback_data": "add_channel_help"}, 
                 {"text": "➖ Remove Channel", "callback_data": "remove_channel_help"}],
                [{"text": "📋 List Channels", "callback_data": "list_channels"}]
            ]
        }
        await self.send_message(chat_id, "📢 <b>Source Channels Management</b>", keyboard)
    
    async def cmd_target(self, chat_id: str, user_id: int):
        """Target command handler (updated)"""
        current_target = self.config.target_channel or "Not set"
        
        keyboard_buttons = []
        if self.config.target_channel:
            keyboard_buttons.append([{"text": "🗑️ Clear Target", "callback_data": "clear_target_confirm"}])
        
        keyboard = {"inline_keyboard": keyboard_buttons} if keyboard_buttons else None
        
        msg = f"""
🎯 <b>Target Channel Management</b>

Current target: <code>{current_target}</code>

To set target channel, send:
<code>/set_target @channel_username</code>
or
<code>/set_target -1001234567890</code> (channel ID)

To clear target channel, send:
<code>/clear_target</code> or use the button below.

<b>Important:</b> Make sure to add this bot as admin to your target channel!
        """
        await self.send_message(chat_id, msg, keyboard)
    
    async def cmd_replacements(self, chat_id: str, user_id: int):
        """Replacements command handler"""
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔗 Links", "callback_data": "manage_links"}, 
                 {"text": "📝 Words", "callback_data": "manage_words"}],
                [{"text": "📄 Sentences", "callback_data": "manage_sentences"}],
                [{"text": "📋 View All", "callback_data": "view_replacements"},
                 {"text": "🗑️ Clear All", "callback_data": "clear_all_replacements"}]
            ]
        }
        await self.send_message(chat_id, "🔧 <b>Text Replacements Management</b>", keyboard)
    
    async def cmd_start_forwarding(self, chat_id: str, user_id: int):
        """Start forwarding command handler"""
        if not self.config.target_channel:
            await self.send_message(chat_id, "❌ Target channel not set. Use /target first.")
            return
        
        if not self.config.source_channels:
            await self.send_message(chat_id, "❌ No source channels added. Use /channels first.")
            return
        
        self.config.forwarding_enabled = True
        self.save_config()
        
        await self.send_message(chat_id, "✅ Forwarding started! The bot will now forward messages from source channels.")
    
    async def cmd_stop_forwarding(self, chat_id: str, user_id: int):
        """Stop forwarding command handler"""
        self.config.forwarding_enabled = False
        self.save_config()
        
        await self.send_message(chat_id, "⏹️ Forwarding stopped!")
    
    async def cmd_help(self, chat_id: str, user_id: int):
        """Help command handler (updated)"""
        help_msg = """
❓ <b>Help - Command Examples</b>

<b>General:</b>
<code>/start</code> - Welcome message
<code>/status</code> - Check bot status
<code>/help</code> - Show this help

<b>Forwarding Control:</b>
<code>/start_forwarding</code> - Activate message forwarding
<code>/stop_forwarding</code> - Deactivate message forwarding

<b>Admin Management:</b>
<code>/admin</code> - Admin management menu (add/remove/list)
<code>/add_admin &lt;user_id&gt;</code>
<code>/remove_admin &lt;user_id&gt;</code>

<b>Channel Management:</b>
<code>/channels</code> - Source channel management menu (add/remove/list)
<code>/add_channel @channelname</code> or <code>/add_channel -1001234567890</code>
<code>/remove_channel @channelname</code> or <code>/remove_channel -1001234567890</code>

<b>Target Channel:</b>
<code>/target</code> - Target channel management menu
<code>/set_target @mytarget</code> or <code>/set_target -1001234567890</code>
<code>/clear_target</code> - Clear currently set target channel

<b>Text Replacements:</b>
<code>/replacements</code> - Replacements management menu
<code>/add_link old.com|new.com</code>
<code>/remove_link old.com</code>
<code>/add_word hello|hi</code>
<code>/remove_word hello</code>
<code>/add_sentence old text|new text</code>
<code>/remove_sentence old text</code>
<code>/clear_replacements all</code> - Clear all replacements
<code>/clear_replacements links</code> - Clear specific type (links/words/sentences)

<b>Quick Setup:</b>
1. Add yourself as admin (if not already): <code>/add_admin your_telegram_user_id</code>
2. Add source channels with <code>/add_channel</code>
3. Set target with <code>/set_target</code>
4. Start forwarding with <code>/start_forwarding</code>

<b>Note:</b> Bot must be added to target channel as admin!
        """
        await self.send_message(chat_id, help_msg)
    
    # Additional command handlers
    async def cmd_add_admin(self, chat_id: str, user_id: int, text: str):
        """Add admin command handler"""
        try:
            parts = text.split()
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/add_admin 123456789</code>")
                return
            
            new_admin_id = int(parts[1])
            if new_admin_id not in self.config.admin_users:
                self.config.admin_users.append(new_admin_id)
                self.save_config()
                await self.send_message(chat_id, f"✅ Added admin: <code>{new_admin_id}</code>")
                logger.info(f"Admin {user_id} added new admin {new_admin_id}.")
            else:
                await self.send_message(chat_id, f"ℹ️ User <code>{new_admin_id}</code> is already an admin.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID. Use numbers only.")
        except Exception as e:
            logger.error(f"Error in cmd_add_admin: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while adding admin.")

    async def cmd_remove_admin(self, chat_id: str, user_id: int, text: str):
        """Remove admin command handler (new)"""
        try:
            parts = text.split()
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/remove_admin 123456789</code>")
                return
            
            admin_to_remove = int(parts[1])
            if admin_to_remove == user_id:
                await self.send_message(chat_id, "❌ You cannot remove yourself as an admin.")
                return
            
            if admin_to_remove in self.config.admin_users:
                self.config.admin_users.remove(admin_to_remove)
                self.save_config()
                await self.send_message(chat_id, f"✅ Removed admin: <code>{admin_to_remove}</code>")
                logger.info(f"Admin {user_id} removed admin {admin_to_remove}.")
            else:
                await self.send_message(chat_id, f"ℹ️ User <code>{admin_to_remove}</code> is not an admin.")
        except ValueError:
            await self.send_message(chat_id, "❌ Invalid user ID. Use numbers only.")
        except Exception as e:
            logger.error(f"Error in cmd_remove_admin: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while removing admin.")
    
    async def cmd_add_channel(self, chat_id: str, user_id: int, text: str):
        """Add channel command handler"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/add_channel @channelname</code> or <code>/add_channel -1001234567890</code>")
                return
            
            channel = parts[1].strip()
            # Normalize channel input for storage and comparison (remove leading '@')
            if channel.startswith('@'):
                channel = channel[1:]
            
            if channel not in [ch.lstrip('@') for ch in self.config.source_channels]: # Compare normalized
                self.config.source_channels.append(channel)
                self.save_config()
                await self.send_message(chat_id, f"✅ Added source channel: <code>{channel}</code>")
                logger.info(f"Admin {user_id} added source channel {channel}.")
            else:
                await self.send_message(chat_id, f"ℹ️ Channel <code>{channel}</code> already added.")
        except Exception as e:
            logger.error(f"Error in cmd_add_channel: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while adding channel.")

    async def cmd_remove_channel(self, chat_id: str, user_id: int, text: str):
        """Remove channel command handler (new)"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/remove_channel @channelname</code> or <code>/remove_channel -1001234567890</code>")
                return
            
            channel_to_remove = parts[1].strip()
            if channel_to_remove.startswith('@'):
                channel_to_remove = channel_to_remove[1:]
            
            # Find the exact channel string in the list, as it might have been stored with or without '@'
            found_channel = None
            for ch in self.config.source_channels:
                if ch.lstrip('@').lower() == channel_to_remove.lower():
                    found_channel = ch
                    break

            if found_channel:
                self.config.source_channels.remove(found_channel)
                self.save_config()
                await self.send_message(chat_id, f"✅ Removed source channel: <code>{found_channel}</code>")
                logger.info(f"Admin {user_id} removed source channel {found_channel}.")
            else:
                await self.send_message(chat_id, f"ℹ️ Channel <code>{channel_to_remove}</code> not found in source channels.")
        except Exception as e:
            logger.error(f"Error in cmd_remove_channel: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while removing channel.")
    
    async def cmd_set_target(self, chat_id: str, user_id: int, text: str):
        """Set target command handler"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/set_target @channelname</code> or <code>/set_target -1001234567890</code>")
                return
            
            target = parts[1].strip()
            # Normalize target channel input (remove leading '@')
            if target.startswith('@'):
                target = target[1:]
            
            if self.config.target_channel == target:
                await self.send_message(chat_id, f"ℹ️ Target channel is already set to: <code>{target}</code>")
                return

            self.config.target_channel = target
            self.save_config()
            
            await self.send_message(chat_id, f"✅ Target channel set to: <code>{target}</code>")
            logger.info(f"Admin {user_id} set target channel to {target}.")
        except Exception as e:
            logger.error(f"Error in cmd_set_target: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while setting target channel.")

    async def cmd_clear_target(self, chat_id: str, user_id: int):
        """Clear target channel (new)"""
        if not self.config.target_channel:
            await self.send_message(chat_id, "ℹ️ No target channel is currently set.")
            return
        
        old_target = self.config.target_channel
        self.config.target_channel = ""
        
        # Stop forwarding if it was active
        if self.config.forwarding_enabled:
            self.config.forwarding_enabled = False
            await self.send_message(chat_id, "⏹️ Forwarding automatically stopped due to target channel being cleared.")
        
        self.save_config()
        await self.send_message(chat_id, f"✅ Target channel cleared. Previous target was: <code>{old_target}</code>")
        logger.info(f"Admin {user_id} cleared target channel ({old_target}).")
    
    async def cmd_add_link(self, chat_id: str, user_id: int, text: str):
        """Add link replacement handler"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2 or '|' not in parts[1]:
                await self.send_message(chat_id, "Usage: <code>/add_link old_link|new_link</code>")
                return
            
            old_link, new_link = parts[1].split('|', 1)
            old_link = old_link.strip()
            new_link = new_link.strip()
            
            if not old_link or not new_link:
                await self.send_message(chat_id, "❌ Both old and new link must be provided.")
                return

            self.config.replacements["links"][old_link] = new_link
            self.save_config()
            await self.send_message(chat_id, f"✅ Added link replacement:\n<code>{old_link}</code> → <code>{new_link}</code>")
            logger.info(f"Admin {user_id} added link replacement: {old_link} -> {new_link}.")
        except Exception as e:
            logger.error(f"Error in cmd_add_link: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while adding link replacement.")

    async def cmd_remove_link(self, chat_id: str, user_id: int, text: str):
        """Remove specific link replacement (new)"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/remove_link &lt;old_link&gt;</code>")
                return
            
            old_link = parts[1].strip()
            
            if old_link in self.config.replacements["links"]:
                removed_replacement = self.config.replacements["links"][old_link]
                del self.config.replacements["links"][old_link]
                self.save_config()
                await self.send_message(chat_id, f"✅ Removed link replacement:\n<code>{old_link}</code> → <code>{removed_replacement}</code>")
                logger.info(f"Admin {user_id} removed link replacement: {old_link}.")
            else:
                await self.send_message(chat_id, f"❌ Link replacement not found: <code>{old_link}</code>")
        except Exception as e:
            logger.error(f"Error in cmd_remove_link: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while removing link replacement.")
    
    async def cmd_add_word(self, chat_id: str, user_id: int, text: str):
        """Add word replacement handler"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2 or '|' not in parts[1]:
                await self.send_message(chat_id, "Usage: <code>/add_word old_word|new_word</code>")
                return
            
            old_word, new_word = parts[1].split('|', 1)
            old_word = old_word.strip()
            new_word = new_word.strip()

            if not old_word or not new_word:
                await self.send_message(chat_id, "❌ Both old and new word must be provided.")
                return
            
            self.config.replacements["words"][old_word] = new_word
            self.save_config()
            await self.send_message(chat_id, f"✅ Added word replacement:\n<code>{old_word}</code> → <code>{new_word}</code>")
            logger.info(f"Admin {user_id} added word replacement: {old_word} -> {new_word}.")
        except Exception as e:
            logger.error(f"Error in cmd_add_word: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while adding word replacement.")

    async def cmd_remove_word(self, chat_id: str, user_id: int, text: str):
        """Remove specific word replacement (new)"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/remove_word &lt;old_word&gt;</code>")
                return
            
            old_word = parts[1].strip()
            
            if old_word in self.config.replacements["words"]:
                removed_replacement = self.config.replacements["words"][old_word]
                del self.config.replacements["words"][old_word]
                self.save_config()
                await self.send_message(chat_id, f"✅ Removed word replacement:\n<code>{old_word}</code> → <code>{removed_replacement}</code>")
                logger.info(f"Admin {user_id} removed word replacement: {old_word}.")
            else:
                await self.send_message(chat_id, f"❌ Word replacement not found: <code>{old_word}</code>")
        except Exception as e:
            logger.error(f"Error in cmd_remove_word: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while removing word replacement.")
    
    async def cmd_add_sentence(self, chat_id: str, user_id: int, text: str):
        """Add sentence replacement handler"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2 or '|' not in parts[1]:
                await self.send_message(chat_id, "Usage: <code>/add_sentence old_sentence|new_sentence</code>")
                return
            
            old_sentence, new_sentence = parts[1].split('|', 1)
            old_sentence = old_sentence.strip()
            new_sentence = new_sentence.strip()

            if not old_sentence or not new_sentence:
                await self.send_message(chat_id, "❌ Both old and new sentence must be provided.")
                return
            
            self.config.replacements["sentences"][old_sentence] = new_sentence
            self.save_config()
            await self.send_message(chat_id, f"✅ Added sentence replacement:\n<code>{old_sentence}</code> → <code>{new_sentence}</code>")
            logger.info(f"Admin {user_id} added sentence replacement: {old_sentence} -> {new_sentence}.")
        except Exception as e:
            logger.error(f"Error in cmd_add_sentence: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while adding sentence replacement.")

    async def cmd_remove_sentence(self, chat_id: str, user_id: int, text: str):
        """Remove specific sentence replacement (new)"""
        try:
            parts = text.split(None, 1)
            if len(parts) != 2:
                await self.send_message(chat_id, "Usage: <code>/remove_sentence &lt;old_sentence&gt;</code>")
                return
            
            old_sentence = parts[1].strip()
            
            if old_sentence in self.config.replacements["sentences"]:
                removed_replacement = self.config.replacements["sentences"][old_sentence]
                del self.config.replacements["sentences"][old_sentence]
                self.save_config()
                await self.send_message(chat_id, f"✅ Removed sentence replacement:\n<code>{old_sentence}</code> → <code>{removed_replacement}</code>")
                logger.info(f"Admin {user_id} removed sentence replacement: {old_sentence}.")
            else:
                await self.send_message(chat_id, f"❌ Sentence replacement not found: <code>{old_sentence}</code>")
        except Exception as e:
            logger.error(f"Error in cmd_remove_sentence: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while removing sentence replacement.")

    async def cmd_clear_replacements(self, chat_id: str, user_id: int, text: str):
        """Clear replacements command handler (new)"""
        parts = text.split()
        if len(parts) == 1:
            # Show help
            await self.send_message(chat_id, """
Usage:
<code>/clear_replacements all</code> - Clear all replacements
<code>/clear_replacements links</code> - Clear link replacements
<code>/clear_replacements words</code> - Clear word replacements  
<code>/clear_replacements sentences</code> - Clear sentence replacements
            """)
            return
        
        replacement_type = parts[1].lower()
        
        try:
            if replacement_type == "all":
                total_count = sum(len(r) for r in self.config.replacements.values())
                if total_count == 0:
                    await self.send_message(chat_id, "ℹ️ No replacements to clear.")
                    return
                
                self.config.replacements = {
                    "links": {},
                    "words": {},
                    "sentences": {}
                }
                self.save_config()
                await self.send_message(chat_id, f"✅ Cleared all {total_count} replacements.")
                logger.info(f"Admin {user_id} cleared all replacements.")
            
            elif replacement_type in ["links", "words", "sentences"]:
                count = len(self.config.replacements[replacement_type])
                if count == 0:
                    await self.send_message(chat_id, f"ℹ️ No {replacement_type} replacements to clear.")
                    return
                
                self.config.replacements[replacement_type] = {}
                self.save_config()
                await self.send_message(chat_id, f"✅ Cleared {count} {replacement_type} replacements.")
                logger.info(f"Admin {user_id} cleared {replacement_type} replacements.")
            
            else:
                await self.send_message(chat_id, "❌ Invalid type. Use: all, links, words, or sentences")
        except Exception as e:
            logger.error(f"Error in cmd_clear_replacements: {e}", exc_info=True)
            await self.send_message(chat_id, "❌ An error occurred while clearing replacements.")

    async def handle_callback_query(self, callback_query):
        """Handle callback queries from inline buttons (updated)"""
        user_id = callback_query["from"]["id"]
        chat_id = str(callback_query["message"]["chat"]["id"])
        data = callback_query["data"]
        callback_query_id = callback_query["id"]
        
        try:
            if not self.is_admin(user_id):
                await self.answer_callback_query(callback_query_id, "❌ Not authorized.", show_alert=True)
                return
            
            # Handle different callback data
            if data == "list_admins":
                admins = self.config.admin_users
                admin_list = "\n".join([f"• <code>{admin_id}</code>" for admin_id in admins]) if admins else "No admins"
                await self.send_message(chat_id, f"👥 <b>Admin Users:</b>\n{admin_list}")
            
            elif data == "list_channels":
                channels = self.config.source_channels
                channel_list = "\n".join([f"• <code>{ch}</code>" for ch in channels]) if channels else "No channels"
                await self.send_message(chat_id, f"📢 <b>Source Channels:</b>\n{channel_list}")
            
            elif data == "view_replacements":
                replacements = self.config.replacements
                msg = "🔧 <b>All Replacements:</b>\n\n"
                
                if replacements["links"]:
                    msg += "🔗 <b>Links:</b>\n"
                    for old, new in replacements["links"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                    msg += "\n"
                
                if replacements["words"]:
                    msg += "📝 <b>Words:</b>\n"
                    for old, new in replacements["words"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                    msg += "\n"
                
                if replacements["sentences"]:
                    msg += "📄 <b>Sentences:</b>\n"
                    for old, new in replacements["sentences"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                
                if not any(replacements.values()):
                    msg += "No replacements configured."
                
                await self.send_message(chat_id, msg)

            # Admin management help buttons
            elif data == "add_admin_help":
                await self.send_message(chat_id, "To add an admin, send: <code>/add_admin &lt;user_id&gt;</code>")
            elif data == "remove_admin_help":
                await self.send_message(chat_id, "To remove an admin, send: <code>/remove_admin &lt;user_id&gt;</code>")
            
            # Channel management help buttons
            elif data == "add_channel_help":
                await self.send_message(chat_id, "To add a channel, send: <code>/add_channel @channel_username</code> or <code>/add_channel -1001234567890</code>")
            elif data == "remove_channel_help":
                await self.send_message(chat_id, "To remove a channel, send: <code>/remove_channel @channel_username</code> or <code>/remove_channel -1001234567890</code>")

            # Target management clear confirmation
            elif data == "clear_target_confirm":
                await self.cmd_clear_target(chat_id, user_id)
            
            # Replacement management buttons
            elif data == "manage_links":
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Add Link", "callback_data": "add_link_help"}, 
                         {"text": "➖ Remove Link", "callback_data": "remove_link_help"}],
                        [{"text": "🗑️ Clear All Links", "callback_data": "clear_links"}],
                        [{"text": "📋 List Links", "callback_data": "list_links"}]
                    ]
                }
                await self.send_message(chat_id, "🔗 <b>Link Replacements Management</b>", keyboard)
            
            elif data == "manage_words":
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Add Word", "callback_data": "add_word_help"}, 
                         {"text": "➖ Remove Word", "callback_data": "remove_word_help"}],
                        [{"text": "🗑️ Clear All Words", "callback_data": "clear_words"}],
                        [{"text": "📋 List Words", "callback_data": "list_words"}]
                    ]
                }
                await self.send_message(chat_id, "📝 <b>Word Replacements Management</b>", keyboard)
            
            elif data == "manage_sentences":
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Add Sentence", "callback_data": "add_sentence_help"}, 
                         {"text": "➖ Remove Sentence", "callback_data": "remove_sentence_help"}],
                        [{"text": "🗑️ Clear All Sentences", "callback_data": "clear_sentences"}],
                        [{"text": "📋 List Sentences", "callback_data": "list_sentences"}]
                    ]
                }
                await self.send_message(chat_id, "📄 <b>Sentence Replacements Management</b>", keyboard)
            
            # Help callbacks for additions/removals
            elif data == "add_link_help":
                await self.send_message(chat_id, "Usage: <code>/add_link old_link|new_link</code>")
            elif data == "remove_link_help":
                await self.send_message(chat_id, "Usage: <code>/remove_link old_link</code>")
            elif data == "add_word_help":
                await self.send_message(chat_id, "Usage: <code>/add_word old_word|new_word</code>")
            elif data == "remove_word_help":
                await self.send_message(chat_id, "Usage: <code>/remove_word old_word</code>")
            elif data == "add_sentence_help":
                await self.send_message(chat_id, "Usage: <code>/add_sentence old_sentence|new_sentence</code>")
            elif data == "remove_sentence_help":
                await self.send_message(chat_id, "Usage: <code>/remove_sentence old_sentence</code>")
            
            # Clear specific types of replacements via callback
            elif data == "clear_links":
                await self.cmd_clear_replacements(chat_id, user_id, "/clear_replacements links")
            elif data == "clear_words":
                await self.cmd_clear_replacements(chat_id, user_id, "/clear_replacements words")
            elif data == "clear_sentences":
                await self.cmd_clear_replacements(chat_id, user_id, "/clear_replacements sentences")
            elif data == "clear_all_replacements":
                await self.cmd_clear_replacements(chat_id, user_id, "/clear_replacements all")
            
            # List specific types of replacements via callback
            elif data == "list_links":
                if self.config.replacements["links"]:
                    msg = "<b>🔗 Link Replacements:</b>\n\n"
                    for old, new in self.config.replacements["links"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                else:
                    msg = "No link replacements configured."
                await self.send_message(chat_id, msg)
            
            elif data == "list_words":
                if self.config.replacements["words"]:
                    msg = "<b>📝 Word Replacements:</b>\n\n"
                    for old, new in self.config.replacements["words"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                else:
                    msg = "No word replacements configured."
                await self.send_message(chat_id, msg)
            
            elif data == "list_sentences":
                if self.config.replacements["sentences"]:
                    msg = "<b>📄 Sentence Replacements:</b>\n\n"
                    for old, new in self.config.replacements["sentences"].items():
                        msg += f"• <code>{old}</code> → <code>{new}</code>\n"
                else:
                    msg = "No sentence replacements configured."
                await self.send_message(chat_id, msg)
            
            # Always answer the callback query to remove loading state
            await self.answer_callback_query(callback_query_id)
        except Exception as e:
            logger.error(f"Error handling callback query '{data}': {e}", exc_info=True)
            await self.answer_callback_query(callback_query_id, "❌ An error occurred.", show_alert=True)
            await self.send_message(chat_id, "❌ An internal error occurred while processing your request.")

    async def get_webhook_info(self):
        """Get current webhook information from Telegram."""
        url = f"{self.base_url}/getWebhookInfo"
        return await self._send_api_request("getWebhookInfo", {})

    async def set_webhook(self, cert_path: Optional[str] = None):
        """
        Set webhook URL for the bot.
        :param cert_path: Path to the public key certificate file (PEM format).
                          Required if your server uses a self-signed certificate.
        """
        if not self.config.webhook_url:
            logger.warning("No webhook URL configured in bot_config.json. Skipping webhook setup.")
            return

        webhook_full_url = f"{self.config.webhook_url}/webhook"
        logger.info(f"Attempting to set webhook to: {webhook_full_url}")

        payload = {
            "url": webhook_full_url,
            "max_connections": 40, # Limit concurrent updates
            "drop_pending_updates": True # Drop updates while bot was offline/reconfiguring
        }

        # If a certificate path is provided, send the certificate file
        if cert_path and os.path.exists(cert_path):
            try:
                with open(cert_path, 'rb') as cert_file:
                    files = {'certificate': cert_file}
                    # For sending files, aiohttp.FormData is typically used or raw multi-part form data
                    # Let's switch to requests for simplicity of file upload in this specific case,
                    # or restructure to use aiohttp.FormData
                    # Sticking to aiohttp.ClientSession for consistency, creating FormData
                    data = aiohttp.FormData()
                    data.add_field('url', webhook_full_url)
                    data.add_field('max_connections', str(payload['max_connections']))
                    data.add_field('drop_pending_updates', 'true')
                    data.add_field('certificate', cert_file.read(), filename=os.path.basename(cert_path), content_type='application/x-pem-file')

                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{self.base_url}/setWebhook", data=data) as response:
                            result = await response.json()
                            if result.get("ok"):
                                logger.info(f"Webhook set successfully to {webhook_full_url} with certificate.")
                            else:
                                logger.error(f"Failed to set webhook with certificate: {result.get('description')}")
                            return result
            except FileNotFoundError:
                logger.error(f"Certificate file not found at: {cert_path}")
                return {"ok": False, "description": "Certificate file not found."}
            except Exception as e:
                logger.error(f"Error setting webhook with certificate: {e}", exc_info=True)
                return {"ok": False, "description": f"Error with certificate: {e}"}
        else:
            # If no cert_path or file not found, proceed without certificate
            logger.warning("No valid certificate path provided for webhook. Setting webhook without certificate.")
            return await self._send_api_request("setWebhook", payload)

    async def delete_webhook(self):
        """Delete webhook URL for the bot."""
        logger.info("Attempting to delete webhook.")
        result = await self._send_api_request("deleteWebhook", {"drop_pending_updates": True})
        if result.get("ok"):
            logger.info("Webhook deleted successfully.")
        else:
            logger.error(f"Failed to delete webhook: {result.get('description')}")
        return result

    async def on_startup(self, app):
        """Actions to perform on bot startup."""
        logger.info("Bot starting up...")
        # Initial admin setup if needed
        if not self.config.admin_users:
            logger.warning("No admin users configured. Please set one using the bot's /start command.")
        
        # Set webhook on startup
        # You would pass your actual certificate path here if you have one.
        # Example: await self.set_webhook(cert_path="/etc/letsencrypt/live/your_domain/fullchain.pem")
        await self.set_webhook() # Call without cert for basic setup, add cert_path for production HTTPS

    async def on_shutdown(self, app):
        """Actions to perform on bot shutdown."""
        logger.info("Bot shutting down...")
        await self.delete_webhook() # Delete webhook on shutdown to prevent missed updates
        self.save_config() # Ensure config is saved one last time
        logger.info("Bot shutdown complete.")

    async def start_webhook(self, cert_file: Optional[str] = None, key_file: Optional[str] = None):
        """
        Starts the aiohttp web server to listen for webhooks.
        :param cert_file: Path to the SSL certificate file for the server (e.g., fullchain.pem).
        :param key_file: Path to the SSL private key file for the server (e.g., privkey.pem).
        """
        self.app.on_startup.append(self.on_startup)
        self.app.on_shutdown.append(self.on_shutdown)

        ssl_context = None
        if self.config.webhook_url.startswith("https://"):
            if cert_file and key_file and os.path.exists(cert_file) and os.path.exists(key_file):
                try:
                    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                    ssl_context.load_cert_chain(cert_file, key_file)
                    logger.info(f"SSL context loaded from {cert_file} and {key_file}. Server will run on HTTPS.")
                except Exception as e:
                    logger.error(f"Error loading SSL certificates: {e}. Falling back to HTTP.", exc_info=True)
                    ssl_context = None
            else:
                logger.warning("Webhook URL is HTTPS but no valid cert/key files provided for aiohttp server. Server will run on HTTP.")
        
        if ssl_context:
            logger.info(f"Starting Aiohttp HTTPS server on port {self.config.webhook_port}...")
        else:
            logger.info(f"Starting Aiohttp HTTP server on port {self.config.webhook_port}...")
        
        # Running the app needs to be done in your main execution script
        # For testing, you can use: web.run_app(self.app, port=self.config.webhook_port, ssl_context=ssl_context)
        # For production, consider gunicorn or similar WSGI servers with aiohttp workers.
        # This method just prepares the app and hooks.

# Example usage in a main script (e.g., main.py)
async def main():
    # Replace with your actual bot token from environment variable or config
    bot_token = os.getenv("BOT_TOKEN") 
    if not bot_token:
        logger.critical("BOT_TOKEN environment variable not set. Exiting.")
        return

    # Replace with your actual webhook URL and desired port
    # For production, this should be your public domain (e.g., https://yourdomain.com)
    # The port should be one accessible from Telegram (80, 443, 88, 8443)
    webhook_url = os.getenv("WEBHOOK_URL", "https://your_domain.com") 
    webhook_port = int(os.getenv("WEBHOOK_PORT", 8443))

    bot = TelegramForwarderBot(bot_token, webhook_url, webhook_port)

    # If this is the first run and no admins are configured, the /start command will guide the user.
    # Otherwise, you can check if self.config.admin_users is empty and prompt for one here too.
    if not bot.config.admin_users:
        logger.info("No admin users found in config. Please send /start to the bot in Telegram to set the first admin.")
    
    # You need to provide your SSL certificate and key files here if you want aiohttp to serve HTTPS directly.
    # In a production environment, it's more common to use a reverse proxy (Nginx, Caddy) for SSL termination.
    # Example for direct Aiohttp HTTPS:
    # cert_file = "/path/to/your/fullchain.pem"
    # key_file = "/path/to/your/privkey.pem"
    cert_file = None
    key_file = None

    # This will set up the webhook on Telegram and start the aiohttp server
    # for production, you'd typically run this with a WSGI server like gunicorn
    # For development/testing:
    try:
        await bot.on_startup(bot.app) # Manually call startup hook for simple run_app
        web.run_app(bot.app, host='0.0.0.0', port=bot.config.webhook_port, ssl_context=None) # No ssl_context needed if reverse proxy handles SSL
                                                                                               # If aiohttp serves HTTPS, pass ssl_context here
    except asyncio.CancelledError:
        logger.info("Application cancelled, initiating shutdown.")
    except Exception as e:
        logger.critical(f"Unhandled error during bot startup/runtime: {e}", exc_info=True)
    finally:
        await bot.on_shutdown(bot.app) # Manually call shutdown hook


if __name__ == "__main__":
    # To run this, you'd typically set environment variables:
    # export BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
    # export WEBHOOK_URL="https://your.public.domain.com"
    # export WEBHOOK_PORT="8443" # Or 443 if you configure your firewall/reverse proxy
    
    # Then run the script: python your_bot_file.py
    
    # For testing without environment variables, uncomment and replace directly:
    # os.environ["BOT_TOKEN"] = "YOUR_BOT_TOKEN"
    # os.environ["WEBHOOK_URL"] = "https://your_ngrok_url.ngrok.io" # Use ngrok for local testing
    # os.environ["WEBHOOK_PORT"] = "8443"

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C).")
    except Exception as e:
        logger.critical(f"Application terminated due to unhandled exception: {e}", exc_info=True)
