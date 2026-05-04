# -*- coding: utf-8 -*-
import json
import os
import logging

logger = logging.getLogger(__name__)

# --- Default Settings ---
DEFAULT_SUPER_ADMIN_ID = 8176454781
DEFAULT_CONFIG = {
    "bot_token": "8208351374:AAGQrNu8Xtis31sdsNIq1TaUtSXcfvEWVdE",
    "admin_username": "AIMAN_DRX",
    "group_id": -1002402598769,
    "per_refer": 3,
    "per_prediction": 3,
    "referral_system_on": True,
    "admin_users": [],
    "super_admin_users": [str(DEFAULT_SUPER_ADMIN_ID)],  # Only super admins can add/remove other admins
    "websites": {
        "Hgzy": {"login_url": "https://hgzy.example.com"},
        "Dkwin": {"login_url": "https://dkwin.example.com"}
    }
}
DEFAULT_CHANNELS = [
    {"name": "HACK Tool", "url": "https://t.me/dkwindeveloper", "id": -1002863838009}
]

# --- Database File Paths ---
DB_CONFIG = "data/config.json"
DB_USERS = "data/users.json"
DB_PREDICTIONS = "data/predictions.json"
DB_ADMINS = "data/admins.json"
DB_CHANNELS = "data/channels.json"

# --- Ensure 'data' directory exists ---
os.makedirs("data", exist_ok=True)

# --- Generic JSON Load/Save Functions ---
def load_json(file_path, default_value):
    """Loads a JSON file, or creates it with a default value if it doesn't exist."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_value, f, indent=4)
        return default_value

def save_json(data, file_path):
    """Saves data to a JSON file."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

# --- Specific Load/Save Functions ---
def load_config():
    return load_json(DB_CONFIG, DEFAULT_CONFIG)

def save_config(data):
    save_json(data, DB_CONFIG)

# --- Initialize and Export Data Variables ---
config = load_config()

# Allow environment variable to override token for local runs
env_token = os.environ.get("BOT_TOKEN")
if env_token:
    config["bot_token"] = env_token

# Ensure super_admin_users key exists and includes the default super admin
if "super_admin_users" not in config or not isinstance(config.get("super_admin_users"), list):
    config["super_admin_users"] = [str(DEFAULT_SUPER_ADMIN_ID)]
    save_config(config)