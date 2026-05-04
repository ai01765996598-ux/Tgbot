# Telegram Bot Admin Command System

This bot includes a comprehensive admin command system that allows administrators to manage users, send broadcasts, and control bot functionality through slash commands. **All admin functions are now command-based with no interactive buttons.**

## 🚀 Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the bot:
```bash
python bot.py
```

## 🔧 Admin Commands

### Core Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/demon` | Show all admin commands | `/demon` |
| `/help` | Show all available commands | `/help` |
| `/broadcast` | Send message to all users | `/broadcast Hello everyone!` |
| `/stats` | Show bot statistics | `/stats` |

### User Management

| Command | Description | Example |
|---------|-------------|---------|
| `/addvipuser` | Add VIP user with time limit | `/addvipuser 123456789 30` |
| `/removevipuser` | Remove VIP status from user | `/removevipuser 123456789` |
| `/banuser` | Ban user from bot | `/banuser 123456789` |
| `/unbanuser` | Unban user | `/unbanuser 123456789` |
| `/setpoints` | Set user points | `/setpoints 123456789 100` |