# Telegram Auto-Forwarder Bot

A powerful Telegram bot that automatically forwards messages from multiple source channels to a target channel with text replacement capabilities.

## Features

- 🔄 **Auto-forwarding** from multiple source channels to a target channel
- 🔧 **Text replacements** (links, words, sentences)
- 👥 **Multi-admin support**
- 🖼️ **Media support** (photos, videos, documents, animations)
- 🔒 **Secure webhook support** with SSL
- 📊 **Status monitoring** and health checks
- 🚀 **Easy deployment** on Render

## Quick Setup

### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Use `/newbot` command and follow instructions
3. Save your bot token (format: `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 2. Deploy on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com)

1. Fork this repository
2. Connect your GitHub account to Render
3. Create a new Web Service from your forked repository
4. Set the following environment variables in Render:
   - `BOT_TOKEN`: Your bot token from BotFather
   - `WEBHOOK_URL`: Your Render app URL (e.g., `https://your-app.onrender.com`)
   - `ADMIN_USERS`: Comma-separated list of admin user IDs (e.g., `123456789,987654321`)

### 3. Configure Your Bot

1. Start a chat with your bot on Telegram
2. Send `/start` to begin setup
3. Use the following commands to configure:

```
/add_channel @source_channel    # Add source channels
/set_target @target_channel     # Set target channel  
/start_forwarding              # Start forwarding
```

## Commands

### Basic Commands
- `/start` - Start the bot and see welcome message
- `/status` - Check bot status and configuration
- `/help` - Show help with command examples

### Channel Management
- `/channels` - Manage source channels
- `/add_channel @channel` - Add a source channel
- `/remove_channel @channel` - Remove a source channel
- `/target` - Manage target channel
- `/set_target @channel` - Set target channel

### Forwarding Control
- `/start_forwarding` - Start message forwarding
- `/stop_forwarding` - Stop message forwarding

### Text Replacements
- `/replacements` - Manage text replacements
- `/add_link old.com|new.com` - Replace links
- `/add_word hello|hi` - Replace words
- `/add_sentence old text|new text` - Replace sentences

### Admin Management
- `/admin` - Admin management menu
- `/add_admin 123456789` - Add new admin
- `/remove_admin 123456789` - Remove admin

## Environment Variables

| Variable | Description | Required | Example |
|----------|-------------|----------|---------|
| `BOT_TOKEN` | Your Telegram bot token | Yes | `123456:ABC-DEF...` |
| `WEBHOOK_URL` | Your app's webhook URL | Yes | `https://your-app.onrender.com` |
| `ADMIN_USERS` | Comma-separated admin user IDs | No | `123456789,987654321` |
| `PORT` | Server port (auto-set by Render) | No | `10000` |

## Setup Instructions

### Getting Channel IDs

To add channels, you need either:
- **Username**: `@channelname` (for public channels)
- **Channel ID**: `-1001234567890` (for any channel)

To get a channel ID:
1. Add [@userinfobot](https://t.me/userinfobot) to your channel
2. It will show the channel ID
3. Remove the bot after getting the ID

### Adding Your Bot to Channels

**For Target Channel:**
1. Add your bot to the target channel as an **administrator**
2. Give it permission to post messages

**For Source Channels:**
- Bot automatically receives updates from **public channels**
- No need to add bot to source channels

## Usage Example

```bash
# 1. Add source channels
/add_channel @news_channel
/add_channel @updates_channel

# 2. Set target channel  
/set_target @my_target_channel

# 3. Add text replacements (optional)
/add_link telegram.org|t.me
/add_word breaking|🚨 BREAKING

# 4. Start forwarding
/start_forwarding
```

## Features in Detail

### Text Replacements
- **Links**: Replace any URL with another URL
- **Words**: Replace specific words (case-insensitive)
- **Sentences**: Replace entire sentences or phrases

### Media Support
- Photos with captions
- Videos with captions  
- Documents and files
- GIFs and animations
- Text messages

### Monitoring
- Health check endpoint: `/health`
- Status endpoint: `/status`
- Real-time logging

## Development

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/yourusername/telegram-forwarder-bot.git
cd telegram-forwarder-bot
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set environment variables:
```bash
export BOT_TOKEN="your_bot_token"
export ADMIN_USERS="your_user_id"
```

4. Run the bot:
```bash
python start.py
```

### Project Structure

```
telegram-forwarder-bot/
├── mainbot.py              # Main bot logic
├── start.py               # Startup script
├── server_manager.py      # Server management
├── requirements.txt       # Python dependencies
├── runtime.txt           # Python version
├── Dockerfile            # Docker configuration
├── render.yaml           # Render deployment config
├── .gitignore           # Git ignore rules
└── README.md            # This file
```

## Troubleshooting

### Common Issues

1. **Bot not responding**: Check if `BOT_TOKEN` is correct
2. **Forwarding not working**: Ensure bot is admin in target channel
3. **Channel not found**: Use correct channel username or ID
4. **Webhook errors**: Verify `WEBHOOK_URL` matches your Render app URL

### Logs

Check logs in Render dashboard or locally:
```bash
tail -f bot.log
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

## Support

- Create an issue for bugs or feature requests
- Check existing issues before creating new ones
- Provide detailed information when reporting issues

## Disclaimer

This bot is for educational and legitimate use only. Make sure to comply with Telegram's Terms of Service and respect copyright laws when forwarding content.