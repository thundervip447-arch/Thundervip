#!/usr/bin/env python3
"""
EGO X NISHAD - Free Fire Tournament System
Complete Single-File Solution for Termux
Run with: python app.py
"""

import os
import sqlite3
import threading
import time
import json
import uuid
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO, emit
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
from werkzeug.utils import secure_filename

# ==================== CONFIGURATION ====================
TELEGRAM_BOT_TOKEN = "8264668307:AAFcWh7amcTMmszJGh5uHX_sQOQ5Nb_YpoY"  # Replace with your bot token
ADMIN_CHAT_ID = "7191892460"  # Replace with your Telegram Chat ID
WEB_HOST = "0.0.0.0"
WEB_PORT = 50001
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# ==================== INITIALIZATION ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ego_nishad_tournament_secret_2026'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)

# Create uploads folder
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs("static", exist_ok=True)

# ==================== DATABASE SETUP ====================
def init_database():
    """Initialize SQLite database with all required tables"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    
    # Players table
    c.execute('''CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid TEXT UNIQUE NOT NULL,
        ingame_name TEXT NOT NULL,
        payment_screenshot TEXT,
        status TEXT DEFAULT 'pending',
        room_id TEXT,
        room_password TEXT,
        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_at TIMESTAMP
    )''')
    
    # Tournament settings table
    c.execute('''CREATE TABLE IF NOT EXISTS tournament_settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )''')
    
    # Insert default tournament settings
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('room_id', 'Not Set Yet'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('room_password', 'Not Set Yet'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('entry_fee', '₹50'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('prize_pool', '₹5,000'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('winner_prize', '₹3,000'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('runner_prize', '₹1,500'))
    c.execute("INSERT OR IGNORE INTO tournament_settings (key, value) VALUES (?, ?)", 
              ('second_runner_prize', '₹500'))
    
    conn.commit()
    conn.close()

def register_player(uid, ingame_name):
    """Register a new player"""
    try:
        conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
        c = conn.cursor()
        c.execute("INSERT INTO players (uid, ingame_name) VALUES (?, ?)", (uid, ingame_name))
        conn.commit()
        player_data = {
            'uid': uid,
            'ingame_name': ingame_name,
            'status': 'pending',
            'registered_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        conn.close()
        return True, player_data
    except sqlite3.IntegrityError:
        return False, "UID already registered!"
    except Exception as e:
        return False, str(e)

def update_payment_screenshot(uid, screenshot_path):
    """Update payment screenshot for a player"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE players SET payment_screenshot = ? WHERE uid = ?", (screenshot_path, uid))
    conn.commit()
    conn.close()

def get_player_by_uid(uid):
    """Get player details by UID"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT uid, ingame_name, status, room_id, room_password FROM players WHERE uid = ?", (uid,))
    player = c.fetchone()
    conn.close()
    if player:
        return {
            'uid': player[0],
            'ingame_name': player[1],
            'status': player[2],
            'room_id': player[3],
            'room_password': player[4]
        }
    return None

def update_player_status(uid, status, room_id=None, room_password=None):
    """Update player approval status and room credentials"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    if status == 'approved':
        c.execute("UPDATE players SET status = ?, approved_at = ?, room_id = ?, room_password = ? WHERE uid = ?",
                 (status, datetime.now().isoformat(), room_id, room_password, uid))
    else:
        c.execute("UPDATE players SET status = ? WHERE uid = ?", (status, uid))
    conn.commit()
    conn.close()

def get_all_pending_players():
    """Get all pending approval players"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT uid, ingame_name, payment_screenshot, registered_at FROM players WHERE status = 'pending' ORDER BY registered_at DESC")
    players = c.fetchall()
    conn.close()
    return players

def get_tournament_settings():
    """Get tournament settings"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT key, value FROM tournament_settings")
    settings = dict(c.fetchall())
    conn.close()
    return settings

def update_tournament_room(room_id, room_password):
    """Update tournament room credentials"""
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE tournament_settings SET value = ? WHERE key = 'room_id'", (room_id,))
    c.execute("UPDATE tournament_settings SET value = ? WHERE key = 'room_password'", (room_password,))
    conn.commit()
    conn.close()
    
    # Also update all approved players with new room credentials
    c.execute("UPDATE players SET room_id = ?, room_password = ? WHERE status = 'approved'", (room_id, room_password))
    conn.commit()
    conn.close()

def is_allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== TELEGRAM BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    """Handle /start command"""
    if str(message.chat.id) == ADMIN_CHAT_ID:
        welcome_msg = """
🔥 *EGO X NISHAD - ADMIN PANEL* 🔥

*Commands:*
/pending - View pending registrations
/approve <UID> - Approve a player
/reject <UID> - Reject a player
/setroom <ID> <PASSWORD> - Set tournament room
/stats - Show tournament statistics
/help - Show this message

*Quick Actions:*
Use inline buttons from payment screenshots for easy approval!
"""
    else:
        welcome_msg = """
🔥 *WELCOME TO EGO X NISHAD TOURNAMENT* 🔥

🎮 *FREE FIRE CUSTOM ROOM TOURNAMENT* 🎮

💰 *Prize Pool:* ₹5,000
🥇 Winner: ₹3,000
🥈 Runner Up: ₹1,500
🥉 2nd Runner Up: ₹500

💵 *Entry Fee:* ₹50

📝 *How to Participate:*
1. Visit our website
2. Register with your UID & IGN
3. Pay ₹50 via QR code
4. Upload payment screenshot
5. Wait for admin approval
6. Get Room ID & Password after approval

🌐 *Website:* http://localhost:50001

*Good luck, fighters!* 🔥
"""
    bot.reply_to(message, welcome_msg, parse_mode='Markdown')

@bot.message_handler(commands=['pending'])
def show_pending(message):
    """Show all pending registrations (Admin only)"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized! Only admin can use this command.")
        return
    
    pending_players = get_all_pending_players()
    if not pending_players:
        bot.reply_to(message, "📭 No pending registrations!")
        return
    
    response = "⏳ *PENDING REGISTRATIONS:*\n\n"
    for player in pending_players[:20]:
        response += f"🆔 UID: `{player[0]}`\n👤 Name: {player[1]}\n📅 Time: {player[3]}\n\n"
    
    bot.reply_to(message, response, parse_mode='Markdown')

@bot.message_handler(commands=['approve'])
def approve_player(message):
    """Approve a player (Admin only)"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Usage: `/approve <UID>`", parse_mode='Markdown')
            return
        
        uid = parts[1]
        settings = get_tournament_settings()
        room_id = settings.get('room_id', 'Not Set')
        room_password = settings.get('room_password', 'Not Set')
        
        update_player_status(uid, 'approved', room_id, room_password)
        bot.reply_to(message, f"✅ Player `{uid}` has been APPROVED!\n\n📡 Room ID: `{room_id}`\n🔑 Password: `{room_password}`", parse_mode='Markdown')
        
        # Notify website via WebSocket
        player = get_player_by_uid(uid)
        if player:
            socketio.emit('player_approved', {
                'uid': uid,
                'room_id': room_id,
                'room_password': room_password
            }, broadcast=True)
            
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['reject'])
def reject_player(message):
    """Reject a player (Admin only)"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized!")
        return
    
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "❌ Usage: `/reject <UID>`", parse_mode='Markdown')
            return
        
        uid = parts[1]
        update_player_status(uid, 'rejected')
        bot.reply_to(message, f"❌ Player `{uid}` has been REJECTED.", parse_mode='Markdown')
        
        # Notify website
        socketio.emit('player_rejected', {'uid': uid}, broadcast=True)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['setroom'])
def set_room(message):
    """Set tournament room credentials (Admin only)"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized!")
        return
    
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "❌ Usage: `/setroom <ROOM_ID> <PASSWORD>`\nExample: `/setroom 1234567890 pass123`", parse_mode='Markdown')
            return
        
        room_id = parts[1]
        room_password = parts[2]
        
        update_tournament_room(room_id, room_password)
        bot.reply_to(message, f"✅ Tournament Room Updated!\n\n📡 Room ID: `{room_id}`\n🔑 Password: `{room_password}`", parse_mode='Markdown')
        
        # Notify all approved players
        socketio.emit('room_updated', {
            'room_id': room_id,
            'room_password': room_password
        }, broadcast=True)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['stats'])
def show_stats(message):
    """Show tournament statistics (Admin only)"""
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized!")
        return
    
    conn = sqlite3.connect('freefire_tournament.db', timeout=20, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM players")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM players WHERE status = 'approved'")
    approved = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM players WHERE status = 'pending'")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM players WHERE status = 'rejected'")
    rejected = c.fetchone()[0]
    conn.close()
    
    stats_msg = f"""
📊 *TOURNAMENT STATISTICS*

👥 Total Registrations: {total}
✅ Approved: {approved}
⏳ Pending: {pending}
❌ Rejected: {rejected}

💰 Prize Pool: ₹5,000
💵 Collection: ₹{total * 50}

Keep up the great work! 🔥
"""
    bot.reply_to(message, stats_msg, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    """Handle inline keyboard callbacks for approval/rejection"""
    if str(call.message.chat.id) != ADMIN_CHAT_ID:
        bot.answer_callback_query(call.id, "Unauthorized!")
        return
    
    data = json.loads(call.data)
    uid = data['uid']
    action = data['action']
    
    if action == 'approve':
        settings = get_tournament_settings()
        room_id = settings.get('room_id', 'Not Set')
        room_password = settings.get('room_password', 'Not Set')
        update_player_status(uid, 'approved', room_id, room_password)
        bot.answer_callback_query(call.id, f"✅ Player {uid} Approved!")
        bot.edit_message_caption(
            f"✅ APPROVED - UID: {uid}\n📡 Room ID: {room_id}\n🔑 Password: {room_password}",
            call.message.chat.id,
            call.message.message_id
        )
        
        # Notify website
        socketio.emit('player_approved', {
            'uid': uid,
            'room_id': room_id,
            'room_password': room_password
        }, broadcast=True)
        
    elif action == 'reject':
        update_player_status(uid, 'rejected')
        bot.answer_callback_query(call.id, f"❌ Player {uid} Rejected!")
        bot.edit_message_caption(
            f"❌ REJECTED - UID: {uid}",
            call.message.chat.id,
            call.message.message_id
        )
        socketio.emit('player_rejected', {'uid': uid}, broadcast=True)

def forward_to_admin(uid, ingame_name, screenshot_path):
    """Forward payment screenshot to admin for approval"""
    try:
        with open(screenshot_path, 'rb') as photo:
            markup = InlineKeyboardMarkup()
            markup.row_width = 2
            markup.add(
                InlineKeyboardButton("✅ Approve", callback_data=json.dumps({'uid': uid, 'action': 'approve'})),
                InlineKeyboardButton("❌ Reject", callback_data=json.dumps({'uid': uid, 'action': 'reject'}))
            )
            
            caption = f"""
🔥 *NEW PAYMENT RECEIVED* 🔥

🆔 *UID:* `{uid}`
👤 *Name:* {ingame_name}
⏰ *Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

*Please verify and approve/reject:*
"""
            bot.send_photo(ADMIN_CHAT_ID, photo, caption=caption, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        print(f"Error forwarding to admin: {e}")

def run_telegram_bot():
    """Run Telegram bot in background thread"""
    print("🤖 Starting Telegram Bot...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=10)
        except Exception as e:
            print(f"⚠️ Bot error: {e}")
            time.sleep(5)

# ==================== FLASK ROUTES & FRONTEND ====================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EGO X NISHAD | Free Fire Tournament</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            background: linear-gradient(135deg, #060000 0%, #0f0000 30%, #1a0000 70%, #0a0000 100%);
            font-family: 'Orbitron', 'Poppins', 'Courier New', monospace;
            min-height: 100vh;
            color: #fff;
            position: relative;
            overflow-x: hidden;
        }

        /* Animated grid background */
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: 
                linear-gradient(rgba(255,0,60,0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,0,60,0.05) 1px, transparent 1px);
            background-size: 40px 40px;
            pointer-events: none;
            z-index: 0;
        }

        /* Cyberpunk Glow Animations */
        @keyframes neonPulse {
            0%, 100% { 
                border-color: #ff003c;
                box-shadow: 0 0 15px rgba(255,0,60,0.5), inset 0 0 10px rgba(255,0,60,0.2);
            }
            50% { 
                border-color: #ff0066;
                box-shadow: 0 0 35px rgba(255,0,60,0.8), inset 0 0 20px rgba(255,0,60,0.4);
            }
        }

        @keyframes textGradient {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        @keyframes glowPulse {
            0% { opacity: 0.7; text-shadow: 0 0 5px #ff003c; }
            100% { opacity: 1; text-shadow: 0 0 25px #ff003c, 0 0 35px #ff0000; }
        }

        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(60px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes borderGlow {
            0% { border-color: #ff003c; box-shadow: 0 0 5px #ff003c; }
            50% { border-color: #ff6699; box-shadow: 0 0 25px #ff003c; }
            100% { border-color: #ff003c; box-shadow: 0 0 5px #ff003c; }
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 2;
        }

        /* Header Section - Premium Cyberpunk */
        .header {
            text-align: center;
            margin-bottom: 50px;
            padding: 35px;
            background: linear-gradient(135deg, rgba(0,0,0,0.85), rgba(30,0,0,0.7));
            border-radius: 30px;
            border: 2px solid #ff003c;
            animation: neonPulse 2s infinite;
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }

        .header::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,0,60,0.1) 0%, transparent 70%);
            animation: glowPulse 3s infinite;
        }

        .avatar-wrapper {
            display: flex;
            justify-content: center;
            margin-bottom: 25px;
        }

        .avatar {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            background: linear-gradient(135deg, #ff003c, #990022);
            padding: 4px;
            animation: neonPulse 1.5s infinite;
        }

        .avatar img {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
            background: #000;
        }

        .logo {
            font-size: 4.5em;
            font-weight: 900;
            background: linear-gradient(135deg, #ff003c, #ff6699, #ff003c, #ff3366);
            background-size: 300% 300%;
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            animation: textGradient 3s ease infinite;
            text-transform: uppercase;
            letter-spacing: 6px;
            margin-bottom: 10px;
            text-shadow: 0 0 20px rgba(255,0,60,0.5);
        }

        .subtitle {
            color: #ff3366;
            font-size: 1.3em;
            letter-spacing: 4px;
            text-transform: uppercase;
            font-weight: 600;
            text-shadow: 0 0 10px rgba(255,0,60,0.5);
        }

        /* Prize Cards - Horizontal 3-Column */
        .prize-section {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 25px;
            margin-bottom: 50px;
        }

        .prize-card {
            background: linear-gradient(135deg, rgba(0,0,0,0.85), rgba(20,0,0,0.75));
            padding: 35px 20px;
            border-radius: 20px;
            text-align: center;
            transition: all 0.3s ease;
            backdrop-filter: blur(8px);
            position: relative;
            overflow: hidden;
        }

        .prize-card::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            width: 100%;
            height: 3px;
            background: linear-gradient(90deg, transparent, #ffd700, transparent);
            transform: scaleX(0);
            transition: transform 0.3s ease;
        }

        .prize-card:hover::after {
            transform: scaleX(1);
        }

        .prize-card:hover {
            transform: translateY(-10px) scale(1.02);
        }

        .prize-card:nth-child(1) {
            border: 2px solid #ffd700;
            box-shadow: 0 0 20px rgba(255,215,0,0.3);
        }
        .prize-card:nth-child(2) {
            border: 2px solid #c0c0c0;
            box-shadow: 0 0 15px rgba(192,192,192,0.3);
        }
        .prize-card:nth-child(3) {
            border: 2px solid #cd7f32;
            box-shadow: 0 0 15px rgba(205,127,50,0.3);
        }

        .prize-amount {
            font-size: 2.8em;
            font-weight: 900;
            margin-bottom: 10px;
        }
        .prize-card:nth-child(1) .prize-amount { color: #ffd700; text-shadow: 0 0 15px #ffd700; }
        .prize-card:nth-child(2) .prize-amount { color: #e0e0e0; text-shadow: 0 0 10px #c0c0c0; }
        .prize-card:nth-child(3) .prize-amount { color: #ffaa44; text-shadow: 0 0 10px #cd7f32; }

        .prize-label {
            font-size: 1.2em;
            letter-spacing: 2px;
            font-weight: 600;
        }

        /* Form Containers - Glassmorphism */
        .form-container, .qr-section, .approval-screen {
            background: rgba(0,0,0,0.7);
            backdrop-filter: blur(15px);
            padding: 40px;
            border-radius: 25px;
            border: 1px solid rgba(255,0,60,0.3);
            transition: all 0.3s ease;
            margin-bottom: 30px;
        }

        .form-container:hover, .qr-section:hover {
            border-color: #ff003c;
            box-shadow: 0 0 30px rgba(255,0,60,0.2);
        }

        .form-group {
            margin-bottom: 25px;
        }

        label {
            display: block;
            margin-bottom: 10px;
            color: #ff3366;
            font-weight: bold;
            letter-spacing: 1px;
            font-size: 0.9em;
            text-transform: uppercase;
        }

        input, .upload-area {
            width: 100%;
            padding: 14px 18px;
            background: rgba(20,20,30,0.8);
            border: 1px solid rgba(255,0,60,0.5);
            border-radius: 12px;
            color: #fff;
            font-size: 1em;
            transition: all 0.3s ease;
            font-family: monospace;
        }

        input:focus {
            outline: none;
            border-color: #ff003c;
            box-shadow: 0 0 20px rgba(255,0,60,0.4);
            background: rgba(0,0,0,0.9);
        }

        /* Premium Button */
        .btn {
            background: linear-gradient(135deg, #ff003c, #cc0030, #ff003c);
            background-size: 200% auto;
            color: #fff;
            padding: 16px 32px;
            border: none;
            border-radius: 50px;
            font-size: 1.2em;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.4s ease;
            width: 100%;
            text-transform: uppercase;
            letter-spacing: 2px;
            font-family: monospace;
        }

        .btn:hover {
            transform: scale(1.03);
            background-position: right center;
            box-shadow: 0 0 25px rgba(255,0,60,0.6);
        }

        /* Payment Section */
        .qr-frame {
            width: 280px;
            height: 280px;
            margin: 20px auto;
            background: linear-gradient(135deg, #1a0000, #0a0000);
            border-radius: 30px;
            padding: 15px;
            border: 2px solid #ff003c;
            transition: all 0.3s ease;
            cursor: pointer;
        }

        .qr-frame:hover {
            transform: scale(1.02);
            box-shadow: 0 0 35px rgba(255,0,60,0.5);
        }

        .qr-frame img {
            width: 100%;
            height: 100%;
            border-radius: 20px;
            object-fit: cover;
        }

        .upi-link {
            color: #ff3366;
            text-decoration: none;
            font-size: 1.2em;
            display: inline-block;
            margin: 15px 0;
            transition: all 0.3s;
        }

        .upi-link:hover {
            color: #ff6699;
            text-shadow: 0 0 8px #ff003c;
        }

        /* Status Screens */
        .approval-screen {
            text-align: center;
        }

        .glass-card {
            background: rgba(0,0,0,0.8);
            backdrop-filter: blur(12px);
            padding: 40px;
            border-radius: 25px;
            border: 1px solid rgba(255,0,60,0.4);
        }

        .room-info {
            background: rgba(0,0,0,0.6);
            padding: 25px;
            border-radius: 15px;
            margin-top: 30px;
            border: 1px solid #00ff66;
        }

        .room-info p {
            margin: 15px 0;
            font-family: 'Courier New', monospace;
            font-size: 1.2em;
        }

        .room-info p strong {
            color: #00ff66;
            text-shadow: 0 0 5px #00ff66;
        }

        .copy-btn {
            background: #00ff66;
            color: #000;
            margin-top: 15px;
            padding: 12px 25px;
            font-size: 1em;
            width: auto;
            display: inline-block;
            font-weight: bold;
        }

        .copy-btn:hover {
            background: #00cc55;
            box-shadow: 0 0 20px #00ff66;
        }

        .loading-pulse {
            animation: borderGlow 1.5s infinite;
            padding: 25px;
            border-radius: 20px;
        }

        @keyframes softPulse {
            0%, 100% { opacity: 0.6; }
            50% { opacity: 1; text-shadow: 0 0 12px #ff003c; }
        }

        .pending-message {
            animation: softPulse 1.5s infinite;
        }

        /* Rejected State */
        .rejected-state {
            border-color: #ff0000;
            background: rgba(255,0,0,0.1);
        }

        .status-badge {
            display: inline-block;
            padding: 6px 18px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
        }

        /* Mobile Responsive */
        @media (max-width: 900px) {
            .prize-section { gap: 15px; }
            .prize-amount { font-size: 1.8em; }
            .logo { font-size: 2.5em; letter-spacing: 3px; }
            .container { padding: 15px; }
        }

        @media (max-width: 700px) {
            .prize-section { grid-template-columns: 1fr; gap: 20px; }
            .prize-card { max-width: 100%; }
            .logo { font-size: 2em; }
            .subtitle { font-size: 0.9em; letter-spacing: 2px; }
            .form-container, .qr-section { padding: 25px; }
        }

        .footer {
            text-align: center;
            margin-top: 60px;
            padding: 25px;
            color: #ff3366;
            border-top: 1px solid rgba(255,0,60,0.3);
            font-size: 0.9em;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="avatar-wrapper">
                <div class="avatar">
                    <img src="/static/logo.jpg" alt="Tournament Logo" onerror="this.src='https://via.placeholder.com/100?text=EGO'">
                </div>
            </div>
            <div class="logo">EGO X NISHAD</div>
            <div class="subtitle">⚡ FREE FIRE CUSTOM ROOM TOURNAMENT ⚡</div>
        </div>

        <div class="prize-section">
            <div class="prize-card">
                <div class="prize-amount">₹3,000</div>
                <div class="prize-label">🥇 WINNER</div>
            </div>
            <div class="prize-card">
                <div class="prize-amount">₹1,500</div>
                <div class="prize-label">🥈 RUNNER UP</div>
            </div>
            <div class="prize-card">
                <div class="prize-amount">₹500</div>
                <div class="prize-label">🥉 2ND RUNNER UP</div>
            </div>
        </div>

        <div id="app">
            <!-- Step 1: Registration -->
            <div id="step1" class="form-container">
                <h2 style="color: #ff003c; margin-bottom: 25px; text-align: center;">🔥 ENTER THE BATTLEGROUND</h2>
                <div class="form-group">
                    <label>🎮 FREE FIRE UID</label>
                    <input type="text" id="uid" placeholder="Enter your unique Free Fire UID" required>
                </div>
                <div class="form-group">
                    <label>👤 IN-GAME NAME (IGN)</label>
                    <input type="text" id="ingameName" placeholder="Your character name" required>
                </div>
                <button class="btn" onclick="registerPlayer()">⚡ REGISTER & CONTINUE ⚡</button>
            </div>

            <!-- Step 2: Payment -->
            <div id="step2" style="display: none;">
                <div class="qr-section">
                    <h2 style="color: #ff003c; text-align: center;">💳 COMPLETE PAYMENT</h2>
                    <p style="margin: 15px 0; text-align: center;">Entry Fee: <strong style="color: #ff003c; font-size: 2em;">₹50</strong></p>
                    
                    <div class="qr-frame" onclick="triggerUPI()">
                        <img src="/static/qr.png" alt="Payment QR Code" onerror="this.src='https://via.placeholder.com/250?text=QR+Code'">
                    </div>
                    
                    <p style="margin: 15px 0; text-align: center;">Scan QR code using any UPI app</p>
                    <p style="text-align: center;">OR</p>
                    <a href="javascript:void(0)" onclick="triggerUPI()" class="upi-link">💸 Click here to pay via UPI 💸</a>
                    
                    <div class="form-group" style="margin-top: 35px;">
                        <label>📸 UPLOAD PAYMENT SCREENSHOT</label>
                        <input type="file" id="screenshot" accept="image/*">
                        <button class="btn" style="margin-top: 18px;" onclick="uploadScreenshot()">🔓 SUBMIT & VERIFY 🔓</button>
                    </div>
                </div>
            </div>

            <!-- Step 3: Approval Status -->
            <div id="step3" style="display: none;">
                <div class="approval-screen">
                    <div id="pendingView" class="glass-card loading-pulse">
                        <div style="font-size: 4em;">⏳</div>
                        <h2 style="color: #ff9933;">PENDING ADMIN APPROVAL</h2>
                        <p>Your payment screenshot has been submitted successfully.</p>
                        <p class="pending-message" style="margin-top: 20px;">Waiting for admin to verify your payment...</p>
                        <p style="margin-top: 25px; font-size: 0.85em; opacity: 0.8;">You will automatically receive room credentials once approved.</p>
                    </div>
                    
                    <div id="approvedView" style="display: none;">
                        <div style="font-size: 4em;">✅</div>
                        <h2 style="color: #00ff66;">APPROVED & READY!</h2>
                        <p>Welcome to the tournament, champion!</p>
                        <div class="room-info">
                            <h3 style="color: #ff003c; margin-bottom: 15px;">🎮 CUSTOM ROOM CREDENTIALS</h3>
                            <p><strong>🏠 ROOM ID:</strong> <span id="roomId">-</span></p>
                            <p><strong>🔑 PASSWORD:</strong> <span id="roomPassword">-</span></p>
                            <button class="btn copy-btn" onclick="copyRoomDetails()">📋 COPY ROOM DETAILS</button>
                        </div>
                    </div>
                    
                    <div id="rejectedView" style="display: none;">
                        <div style="font-size: 4em;">❌</div>
                        <h2 style="color: #ff0000;">PAYMENT REJECTED</h2>
                        <p>Your payment could not be verified. Please contact admin for support.</p>
                        <button class="btn" onclick="location.reload()">🔄 TRY AGAIN</button>
                    </div>
                </div>
            </div>
        </div>

        <div class="footer">
            <p>🔥 <strong>EGO X NISHAD</strong> presents the ultimate Free Fire Tournament experience 🔥</p>
            <p>Contact Admin on Telegram for support | #RoadToVictory</p>
        </div>
    </div>

    <script>
        const socket = io();
        let currentUID = null;
        
        function registerPlayer() {
            const uid = document.getElementById('uid').value.trim();
            const ingameName = document.getElementById('ingameName').value.trim();
            
            if (!uid || !ingameName) {
                alert('⚠️ Please fill in both UID and In-Game Name!');
                return;
            }
            
            if (!/^\\d+$/.test(uid)) {
                alert('❌ UID must contain only numbers!');
                return;
            }
            
            fetch('/api/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({uid: uid, ingame_name: ingameName})
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    currentUID = uid;
                    document.getElementById('step1').style.display = 'none';
                    document.getElementById('step2').style.display = 'block';
                } else {
                    alert('Registration failed: ' + data.message);
                }
            })
            .catch(err => alert('Network error: ' + err));
        }
        
        function triggerUPI() {
            const upiUrl = "upi://pay?pa=legendthunder1@ybl&pn=EGO%20X%20NISHAD&am=50&cu=INR";
            window.open(upiUrl, '_blank');
        }
        
        function uploadScreenshot() {
            const fileInput = document.getElementById('screenshot');
            const file = fileInput.files[0];
            
            if (!file) {
                alert('📸 Please select a payment screenshot first!');
                return;
            }
            
            const formData = new FormData();
            formData.append('screenshot', file);
            formData.append('uid', currentUID);
            
            fetch('/api/upload_payment', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('step2').style.display = 'none';
                    document.getElementById('step3').style.display = 'block';
                    checkStatus();
                } else {
                    alert('Upload failed: ' + data.message);
                }
            })
            .catch(err => alert('Upload error: ' + err));
        }
        
        function checkStatus() {
            if (!currentUID) return;
            
            fetch(`/api/player_status?uid=${currentUID}`)
            .then(res => res.json())
            .then(data => {
                if (data.status === 'approved') {
                    document.getElementById('pendingView').style.display = 'none';
                    document.getElementById('approvedView').style.display = 'block';
                    document.getElementById('roomId').textContent = data.room_id || 'Not Set';
                    document.getElementById('roomPassword').textContent = data.room_password || 'Not Set';
                } else if (data.status === 'rejected') {
                    document.getElementById('pendingView').style.display = 'none';
                    document.getElementById('rejectedView').style.display = 'block';
                }
            });
        }
        
        function copyRoomDetails() {
            const roomId = document.getElementById('roomId').textContent;
            const roomPass = document.getElementById('roomPassword').textContent;
            const text = `🎮 Free Fire Room Details\n━━━━━━━━━━━━━━━━━━\n📡 Room ID: ${roomId}\n🔑 Password: ${roomPass}\n━━━━━━━━━━━━━━━━━━\n🔥 EGO X NISHAD Tournament 🔥`;
            navigator.clipboard.writeText(text);
            alert('✅ Room details copied to clipboard!');
        }
        
        // Socket.IO real-time events
        socket.on('connect', () => {
            console.log('Connected to tournament server');
            if (currentUID) checkStatus();
        });
        
        socket.on('player_approved', (data) => {
            if (data.uid === currentUID) {
                document.getElementById('pendingView').style.display = 'none';
                document.getElementById('approvedView').style.display = 'block';
                document.getElementById('roomId').textContent = data.room_id;
                document.getElementById('roomPassword').textContent = data.room_password;
            }
        });
        
        socket.on('player_rejected', (data) => {
            if (data.uid === currentUID) {
                document.getElementById('pendingView').style.display = 'none';
                document.getElementById('rejectedView').style.display = 'block';
            }
        });
        
        socket.on('room_updated', (data) => {
            if (currentUID && document.getElementById('approvedView').style.display !== 'none') {
                document.getElementById('roomId').textContent = data.room_id;
                document.getElementById('roomPassword').textContent = data.room_password;
            }
        });
        
        // Fallback polling every 5 seconds
        setInterval(() => {
            if (currentUID && document.getElementById('pendingView').style.display !== 'none') {
                checkStatus();
            }
        }, 50001);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Serve the tournament page"""
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/register', methods=['POST'])
def api_register():
    """Register a new player"""
    data = request.json
    uid = data.get('uid')
    ingame_name = data.get('ingame_name')
    
    success, result = register_player(uid, ingame_name)
    return jsonify({'success': success, 'message': result if not success else 'Registered'})

@app.route('/api/upload_payment', methods=['POST'])
def api_upload_payment():
    """Upload payment screenshot"""
    uid = request.form.get('uid')
    file = request.files.get('screenshot')
    
    if not file or not is_allowed_file(file.filename):
        return jsonify({'success': False, 'message': 'Invalid file type'})
    
    # Generate unique filename
    ext = file.filename.rsplit('.', 1)[1].lower()
    filename = f"{uid}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Update database
    update_payment_screenshot(uid, filepath)
    
    # Get player details and forward to admin
    player = get_player_by_uid(uid)
    if player:
        forward_to_admin(uid, player['ingame_name'], filepath)
    
    return jsonify({'success': True})

@app.route('/api/player_status', methods=['GET'])
def api_player_status():
    """Get player status"""
    uid = request.args.get('uid')
    player = get_player_by_uid(uid)
    if player:
        return jsonify(player)
    return jsonify({'status': 'not_found'})

# Dummy static route for logo and QR (placeholder files)
@app.route('/static/<path:filename>')
def static_files(filename):
    """Serve static files with fallback"""
    from flask import send_from_directory, abort
    filepath = os.path.join('static', filename)
    if os.path.exists(filepath):
        return send_from_directory('static', filename)
    # Return a data URI placeholder if file doesn't exist
    if filename == 'logo.jpg':
        return '''
        <svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
            <circle cx="50" cy="50" r="45" fill="url(#grad)" stroke="#ff003c" stroke-width="3"/>
            <defs><radialGradient id="grad"><stop offset="0%" stop-color="#ff003c"/><stop offset="100%" stop-color="#660011"/></radialGradient></defs>
            <text x="50" y="65" font-size="20" text-anchor="middle" fill="white" font-weight="bold">E N</text>
        </svg>
        ''', 200, {'Content-Type': 'image/svg+xml'}
    elif filename == 'qr.png':
        return '''
        <svg width="250" height="250" xmlns="http://www.w3.org/2000/svg">
            <rect width="250" height="250" fill="#000"/>
            <rect x="50" y="50" width="150" height="150" fill="#ff003c" rx="10"/>
            <text x="125" y="140" font-size="18" text-anchor="middle" fill="white" font-weight="bold">PAY HERE</text>
            <text x="125" y="165" font-size="14" text-anchor="middle" fill="white">SCAN QR</text>
        </svg>
        ''', 200, {'Content-Type': 'image/svg+xml'}
    abort(404)

@socketio.on('connect')
def handle_connect():
    print('Client connected to WebSocket')

# ==================== MAIN ENTRY POINT ====================
if __name__ == '__main__':
    print("=" * 60)
    print("🔥 EGO X NISHAD - FREE FIRE TOURNAMENT SYSTEM 🔥")
    print("=" * 60)
    
    # Create placeholder static files if missing
    if not os.path.exists('static/logo.jpg'):
        with open('static/logo.jpg', 'w') as f:
            f.write('')  # Placeholder, will be served by SVG route
    if not os.path.exists('static/qr.png'):
        with open('static/qr.png', 'w') as f:
            f.write('')
    
    # Initialize database
    init_database()
    print("✅ Database initialized")
    
    # Check configuration
    if TELEGRAM_BOT_TOKEN == "8264668307:AAFcWh7amcTMmszJGh5uHX_sQOQ5Nb_YpoY":
        print("⚠️ WARNING: Using default Bot Token. Replace it with your own from @BotFather")
    if ADMIN_CHAT_ID == "7191892460":
        print("⚠️ WARNING: Using default Admin Chat ID. Replace it with your Telegram ID")
    else:
        # Start Telegram bot in background
        bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
        bot_thread.start()
        print("✅ Telegram bot thread started")
    
    print("=" * 60)
    print(f"🌐 Website: http://{WEB_HOST}:{WEB_PORT}")
    print("📱 Open in browser to start registration")
    print("⚡ Press Ctrl+C to stop")
    print("=" * 60)
    
    socketio.run(app, host=WEB_HOST, port=WEB_PORT, debug=False, allow_unsafe_werkzeug=True)