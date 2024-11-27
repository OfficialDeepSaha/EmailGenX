import os
import sqlite3
import requests
from fastapi import FastAPI, HTTPException
import telebot
from multiprocessing import Process
import uvicorn
from dotenv import load_dotenv
import random
import string

# Load Environment Variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("Telegram bot token is missing. Set it in the .env file.")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Database Initialization
DB_FILE = "emailgenx.db"

def initialize_db():
    """Initialize the SQLite database."""
    if not os.path.exists(DB_FILE):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE users (
                chat_id INTEGER PRIMARY KEY,
                email TEXT,
                token TEXT,
                inbox TEXT
            )
        """)
        conn.commit()
        conn.close()
initialize_db()

# FastAPI App
app = FastAPI()

# Helper Functions
def generate_short_id(length=8):
    """Generate a short random string of specified length."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def create_temp_email(chat_id):
    """Create a temporary email and store token."""
    try:
        # Step 1: Get the domain dynamically
        domain_response = requests.get("https://api.mail.tm/domains")
        domain_response.raise_for_status()
        domain_data = domain_response.json()
        domains = domain_data.get("hydra:member", [])
        if not domains:
            print("No domains available.")
            return None

        # Use the first domain from the list
        domain = domains[0]["domain"]
        short_id = generate_short_id()  # Generate a short random ID
        email = f"user_{short_id}@{domain}"
        password = f"secure_{short_id}"  # Use short ID as part of the password for uniqueness

        # Step 2: Create account
        response = requests.post(
            "https://api.mail.tm/accounts",
            json={"address": email, "password": password}
        )
        response.raise_for_status()  # Raises an HTTPError if the response is not 2xx

        # Parse account creation response
        data = response.json()

        # Step 3: Generate token
        token_response = requests.post(
            "https://api.mail.tm/token",
            json={"address": email, "password": password}
        )
        token_response.raise_for_status()
        token = token_response.json().get("token")

        # Step 4: Store in database
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO users (chat_id, email, token, inbox) VALUES (?, ?, ?, ?)", 
                  (chat_id, email, token, "[]"))
        conn.commit()
        conn.close()
        return email
    except requests.RequestException as e:
        print(f"Error creating temp email: {e}")
        print(f"Domain Response: {domain_response.content}")
        if response:
            print(f"Account Creation Response: {response.content}")
        return None


def get_user_email(chat_id):
    """Retrieve the user's email from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT email FROM users WHERE chat_id = ?", (chat_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None

def get_user_token(chat_id):
    """Retrieve the user's token from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT token FROM users WHERE chat_id = ?", (chat_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return None

def get_inbox(chat_id):
    """Fetch inbox messages for the user's email."""
    token = get_user_token(chat_id)
    if not token:
        return None
    try:
        response = requests.get(
            "https://api.mail.tm/messages",
            headers={"Authorization": f"Bearer {token}"}
        )
        response.raise_for_status()
        return response.json().get("hydra:member", [])
    except requests.RequestException as e:
        print(f"Error fetching inbox: {e}")
        return []

def delete_temp_email(chat_id):
    """Delete the user's temporary email from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"Database error: {e}")

# Telegram Bot Handlers
@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(message, "Welcome to EmailGenX! Use /generate to create a temporary email address.")

@bot.message_handler(commands=["generate"])
def generate_email(message):
    chat_id = message.chat.id
    email = create_temp_email(chat_id)
    if email:
        bot.reply_to(message, f"Your temporary email address is: {email}\nUse it to receive messages here.")
    else:
        bot.reply_to(message, "Failed to generate email. Please try again later.")

@bot.message_handler(commands=["inbox"])
def inbox(message):
    chat_id = message.chat.id
    messages = get_inbox(chat_id)
    if messages:
        inbox_summary = "\n\n".join([f"From: {msg['from']['address']}\nSubject: {msg['subject']}" for msg in messages])
        bot.reply_to(message, f"Your Inbox:\n\n{inbox_summary}")
    else:
        bot.reply_to(message, "Your inbox is empty or no email address is linked. Use /generate to create one.")

@bot.message_handler(commands=["delete"])
def delete_email(message):
    chat_id = message.chat.id
    delete_temp_email(chat_id)
    bot.reply_to(message, "Your temporary email address has been deleted.")

@bot.message_handler(commands=["help"])
def help_message(message):
    help_text = """
    💌 **EmailGenX Commands**:
    /start – Start using EmailGenX.
    /generate – Create a new temporary email.
    /inbox – View your received emails.
    /delete – Remove the temporary email.
    /help – Get detailed guidance on using the bot.
    """
    bot.reply_to(message, help_text)

# Process Definitions
def start_bot():
    """Start the Telegram bot."""
    bot.polling(non_stop=True, interval=0)

def start_api():
    """Start the FastAPI server."""
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    # Create separate processes for the bot and the FastAPI server
    bot_process = Process(target=start_bot)
    api_process = Process(target=start_api)

    # Start both processes
    bot_process.start()
    api_process.start()

    # Wait for both processes to complete
    bot_process.join()
    api_process.join()
