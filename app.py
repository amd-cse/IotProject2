import os
import json
import base64
import numpy as np
import cv2
import face_recognition
import requests
import time
import threading
import telebot
import os
import uuid
from functools import wraps
from werkzeug.security import check_password_hash
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this'

# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = "8555366858:AAFpPzk1mEaDuHW49-k2FCv5tSQDD_sxMjc"
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False)

# --- Admin Configuration ---
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

def upload_to_imgbb(image_data):
    try:
        # Extract base64 encoded string from "data:image/jpeg;base64,..."
        b64_string = image_data.split(',')[1]
        
        payload = {
            "key": IMGBB_API_KEY,
            "image": b64_string
        }
        res = requests.post("https://api.imgbb.com/1/upload", data=payload, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            return data["data"]["url"]
        else:
            print(f"ImgBB API error: {res.text}")
            return None
    except Exception as e:
        print(f"ImgBB Exception: {e}")
        return None

# ==========================================
# ACCESS LOGGING SYSTEM
# ==========================================
ACCESS_LOGS_DB = 'data/access_logs.json'
os.makedirs('data', exist_ok=True)
if not os.path.exists(ACCESS_LOGS_DB):
    with open(ACCESS_LOGS_DB, 'w') as f:
        json.dump([], f)

def load_access_logs():
    try:
        with open(ACCESS_LOGS_DB, 'r') as f:
            return json.load(f)
    except:
        return []

def save_access_logs(logs):
    with open(ACCESS_LOGS_DB, 'w') as f:
        json.dump(logs, f, indent=2)

def log_access_attempt(user_name, status, message, image_data=None, std_dev=None, glare_ratio=None, euclidean_distance=None):
    photo_url = None
    if image_data and IMGBB_API_KEY:
        photo_url = upload_to_imgbb(image_data)
        
    def safe_float(val):
        return float(val) if val is not None else None
        
    log_entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.now().isoformat(),
        "user": user_name,
        "status": status,
        "message": message,
        "photo_url": photo_url,
        "std_dev": safe_float(std_dev),
        "glare_ratio": safe_float(glare_ratio),
        "euclidean_distance": safe_float(euclidean_distance)
    }
    
    logs = load_access_logs()
    logs.insert(0, log_entry)  # Add to beginning
    if len(logs) > 100:  # Keep last 100
        logs = logs[:100]
    save_access_logs(logs)

# ==========================================
# AUTHENTICATION DECORATOR
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, f"Welcome to Smart Locker!\nYour Chat ID is: {message.chat.id}\nUse this ID during enrollment. Send /unlock to remotely open the locker.")

@bot.message_handler(commands=['unlock'])
def unlock_command(message):
    chat_id = str(message.chat.id)
    users = load_users()
    authorized_user = None
    for name, udata in users.items():
        if str(udata.get('telegram_chat_id', '')) == chat_id:
            authorized_user = name
            break
            
    if authorized_user:
        bot.reply_to(message, f"Authorized ({authorized_user}). Unlocking door...")
        trigger_esp32_door_open()
    else:
        bot.reply_to(message, "Unauthorized. Your Chat ID is not enrolled in the system.")

def start_bot():
    print("Starting Telegram Bot...")
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"Telegram Bot error: {e}")

bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()

def notify_telegram_user(chat_id, message, image_data=None):
    if not chat_id:
        return
    try:
        if image_data:
            image_bytes = base64.b64decode(image_data.split(',')[1])
            bot.send_photo(chat_id, image_bytes, caption=message)
        else:
            bot.send_message(chat_id, message)
    except Exception as e:
        print(f"Telegram notification error: {e}")

USERS_DB = 'data/users.json'
os.makedirs('data', exist_ok=True)
if not os.path.exists(USERS_DB):
    with open(USERS_DB, 'w') as f:
        json.dump({}, f)

# --- ESP32 Configuration ---
ESP32_IP = "192.168.137.16"  # Replace with your ESP32 IP
ESP32_LED_ON_URL = f"http://{ESP32_IP}/led/on"
ESP32_LED_OFF_URL = f"http://{ESP32_IP}/led/off"
ESP32_RFID_POP_URL = f"http://{ESP32_IP}/rfid/pop"
ESP32_DOOR_OPEN_URL = f"http://{ESP32_IP}/door/open"

# --- Global State ---
# system_mode can be "auth" (default) or "enrolling"
system_state = {
    "mode": "auth",
    "locker_status": "idle",
    "pending_user": None,
    "message": "System Idle. Scan RFID to begin."
}

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def load_users():
    try:
        with open(USERS_DB, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    with open(USERS_DB, 'w') as f:
        json.dump(users, f, indent=2)

def calculate_blue_ratio(image_array):
    hsv = cv2.cvtColor(image_array, cv2.COLOR_BGR2HSV)
    lower_blue = np.array([100, 50, 50])
    upper_blue = np.array([140, 255, 255])
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    blue_pixels = np.sum(mask > 0)
    total_pixels = image_array.shape[0] * image_array.shape[1]
    return blue_pixels / (total_pixels + 1e-6)

# --- OLD LIVENESS CHECK ---
# def verify_blue_light(ambient_frame_data, illuminated_frame_data):
#     try:
#         ambient_bytes = base64.b64decode(ambient_frame_data.split(',')[1])
#         ambient_img = np.array(Image.open(BytesIO(ambient_bytes)))[:, :, ::-1].copy()
#         
#         illuminated_bytes = base64.b64decode(illuminated_frame_data.split(',')[1])
#         illuminated_img = np.array(Image.open(BytesIO(illuminated_bytes)))[:, :, ::-1].copy()
#         
#         face_locations = face_recognition.face_locations(illuminated_img)
#         if len(face_locations) == 0:
#             return False, "No face detected during liveness check"
#         
#         top, right, bottom, left = face_locations[0]
#         ambient_face = ambient_img[top:bottom, left:right]
#         illuminated_face = illuminated_img[top:bottom, left:right]
#         
#         ambient_ratio = calculate_blue_ratio(ambient_face)
#         illuminated_ratio = calculate_blue_ratio(illuminated_face)
#         
#         if illuminated_ratio > 0.05 and illuminated_ratio > ambient_ratio * 2.0:
#             return True, "Liveness verified"
#         else:
#             return False, "Blue light change not detected"
#     except Exception as e:
#         return False, f"Error: {str(e)}"

# --- NEW ADVANCED LIVENESS CHECK ---
def verify_blue_light(ambient_frame_data, illuminated_frame_data):
    try:
        # 1. Decode images
        ambient_bytes = base64.b64decode(ambient_frame_data.split(',')[1])
        ambient_img = np.array(Image.open(BytesIO(ambient_bytes)))[:, :, ::-1].copy()
        
        illuminated_bytes = base64.b64decode(illuminated_frame_data.split(',')[1])
        illuminated_img = np.array(Image.open(BytesIO(illuminated_bytes)))[:, :, ::-1].copy()
        
        # 2. Find the face
        face_locations = face_recognition.face_locations(illuminated_img)
        if len(face_locations) == 0:
            return False, "No face detected during liveness check", None, None
        
        top, right, bottom, left = face_locations[0]
        ambient_face = ambient_img[top:bottom, left:right]
        illuminated_face = illuminated_img[top:bottom, left:right]
        
        # 3. Base check: Did the blue ratio increase? 
        ambient_ratio = calculate_blue_ratio(ambient_face)
        illuminated_ratio = calculate_blue_ratio(illuminated_face)
        
        if not (illuminated_ratio > 0.05 and illuminated_ratio > ambient_ratio * 1.5):
             # Phone screens often fail this because their backlight overpowers the LED
            return False, "Blue light change not detected (Possible Screen/Backlight)", None, None

        # --- ADVANCED LIVENESS CHECKS ---
        
        # Extract just the Blue channels (OpenCV uses BGR, so index 0 is Blue)
        # Convert to int16 to prevent underflow when subtracting
        ambient_b = ambient_face[:, :, 0].astype(np.int16)
        illuminated_b = illuminated_face[:, :, 0].astype(np.int16)
        
        # Get the difference image (how much blue light was ADDED by the LED)
        diff_b = np.clip(illuminated_b - ambient_b, 0, 255).astype(np.uint8)

        # A. Detect Screen/Glass Glare (Specular Highlight)
        # Glare from glass will saturate the camera sensor (value near 255).
        # We check if a pixel is saturated in the illuminated frame AND it increased due to the LED.
        glare_mask = (illuminated_b > 240) & (diff_b > 30)
        glare_pixels = np.sum(glare_mask)
        total_pixels = diff_b.shape[0] * diff_b.shape[1]
        glare_ratio = glare_pixels / float(total_pixels)
        
        print(f"[CALIBRATION] Max Illuminated Blue: {np.max(illuminated_b)}, Max Blue Diff: {np.max(diff_b)}")
        print(f"[CALIBRATION] Glare Ratio: {glare_ratio:.4f} (Threshold: > 0.015 fails)")
        
        # B. Detect Flat 2D Surfaces (Matte Photos)
        # Calculate how "uneven" the light reflection is. 
        # 3D faces = uneven (high std), Flat paper = uniform (low std)
        std_dev = np.std(diff_b)
        tuned_threshold = 12.0 # Increased from 12.0 to 14.0 for better sensitivity
        print(f"[CALIBRATION] Standard Deviation: {std_dev:.2f} (Threshold: < {tuned_threshold} fails)")
        
        if glare_ratio > 0.015: # If more than 1.5% of the face is pure glare
            return False, "Screen or glossy photo detected (Glass Glare)", std_dev, glare_ratio
            
        if std_dev < tuned_threshold: 
            return False, "2D photo detected (Flat Reflection)", std_dev, glare_ratio
            
        return True, "Liveness verified", std_dev, glare_ratio
    except Exception as e:
        return False, f"Error: {str(e)}", None, None

def pop_esp32_rfid():
    """Polls ESP32 for a scanned RFID UID. Returns UID or None."""
    try:
        res = requests.get(ESP32_RFID_POP_URL, timeout=1.0)
        data = res.json()
        uid = data.get("uid", "").strip()
        return uid if uid else None
    except:
        return None

def trigger_esp32_door_open():
    """Sends command to ESP32 to open the door."""
    try:
        requests.post(ESP32_DOOR_OPEN_URL, timeout=1.0)
    except:
        pass

# ==========================================
# ENROLLMENT ROUTES
# ==========================================
@app.route('/enroll', methods=['GET', 'POST'])
@login_required
def enroll():
    global system_state
    if request.method == 'POST':
        data = request.json
        name = data.get('name')
        telegram_chat_id = data.get('telegram_chat_id', '')
        rfid_uid = data.get('rfid_uid', '').replace(" ", "").upper()
        images = data.get('images', [])
        
        if not name or not rfid_uid or not images:
            return jsonify({'success': False, 'message': 'Name, RFID UID, and images are required'})
        
        users = load_users()
        for u, data in users.items():
            if data.get('rfid_uid', '').replace(" ", "").upper() == rfid_uid:
                return jsonify({'success': False, 'message': 'RFID UID already enrolled'})
        
        encodings = []
        for img_data in images:
            try:
                image_bytes = base64.b64decode(img_data.split(',')[1])
                image = Image.open(BytesIO(image_bytes))
                image_array = np.array(image)[:, :, ::-1].copy()
                encodings_list = face_recognition.face_encodings(image_array)
                if encodings_list:
                    encodings.append(encodings_list[0].tolist())
            except:
                continue
        
        if len(encodings) < 3:
            return jsonify({'success': False, 'message': 'Need at least 3 good images'})
        
        avg_encoding = np.mean(encodings, axis=0).tolist()
        users[name] = {
            'rfid_uid': rfid_uid,
            'telegram_chat_id': telegram_chat_id,
            'encodings': encodings,
            'avg_encoding': avg_encoding,
            'enrollment_date': datetime.now().isoformat()
        }
        save_users(users)
        
        # Return system to auth mode
        system_state["mode"] = "auth"
        system_state["locker_status"] = "idle"
        system_state["message"] = "System Idle. Scan RFID to begin."
        
        return jsonify({'success': True, 'message': f'User {name} enrolled successfully'})
    
    # When page loads, set mode to enrolling
    system_state["mode"] = "enrolling"
    system_state["locker_status"] = "idle"
    system_state["message"] = "Enrollment Mode. Scan RFID card."
    return render_template('enroll.html')

@app.route('/api/enrollment/scan_rfid', methods=['GET'])
@login_required
def enrollment_scan_rfid():
    """Called by browser to check if ESP32 has an RFID UID during enrollment"""
    if system_state["mode"] != "enrolling":
        return jsonify({'success': False, 'message': 'Not in enrollment mode'})
    
    uid = pop_esp32_rfid()
    if uid:
        return jsonify({'success': True, 'uid': uid})
    return jsonify({'success': False})

@app.route('/api/enrollment/cancel', methods=['POST'])
@login_required
def enrollment_cancel():
    """Return system to auth mode if user cancels enrollment"""
    system_state["mode"] = "auth"
    system_state["locker_status"] = "idle"
    system_state["message"] = "System Idle. Scan RFID to begin."
    return jsonify({'success': True})

# ==========================================
# DASHBOARD & AUTHENTICATION ROUTES
# ==========================================
@app.route('/')
def index():
    return redirect(url_for('locker'))

@app.route('/locker')
def locker():
    global system_state
    system_state["mode"] = "auth"
    system_state["locker_status"] = "idle"
    system_state["message"] = "System Idle. Scan RFID to begin."
    return render_template('locker.html')

@app.route('/authenticate')
def authenticate():
    global system_state
    system_state["mode"] = "auth"
    return render_template('authenticate.html')

# ==========================================
# ADMIN DASHBOARD ROUTES
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session['logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error="Invalid credentials")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin_dashboard():
    return render_template('admin.html')

@app.route('/api/admin/logs', methods=['GET'])
@login_required
def get_logs():
    return jsonify(load_access_logs())

@app.route('/api/admin/users', methods=['GET'])
@login_required
def get_users():
    return jsonify(load_users())

@app.route('/api/admin/users/<name>', methods=['DELETE'])
@login_required
def delete_user(name):
    users = load_users()
    if name in users:
        del users[name]
        save_users(users)
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "User not found"})

@app.route('/api/admin/unlock', methods=['POST'])
@login_required
def remote_unlock():
    trigger_esp32_door_open()
    log_access_attempt("Admin", "Success", "Remote Unlock via Dashboard")
    return jsonify({"success": True})

@app.route('/api/locker/status', methods=['GET'])
def api_locker_status():
    """Called by dashboard browser to check for RFID scans and trigger auth"""
    global system_state
    
    if system_state["mode"] == "auth" and system_state["locker_status"] == "idle":
        # Poll ESP32 for RFID
        uid = pop_esp32_rfid()
        if uid:
            users = load_users()
            found_user = None
            for name, udata in users.items():
                if udata.get('rfid_uid', '').replace(" ", "").upper() == uid:
                    found_user = name
                    break
            
            if found_user:
                system_state["locker_status"] = "awaiting_face"
                system_state["pending_user"] = found_user
                system_state["message"] = f"RFID Accepted. Awaiting face for {found_user}."
            else:
                system_state["locker_status"] = "idle"
                system_state["message"] = "Access Denied: Unknown RFID card."
    
    return jsonify(system_state)

@app.route('/liveness/start', methods=['POST'])
def start_liveness():
    try:
        requests.get(ESP32_LED_ON_URL, timeout=2.0)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/authenticate_face', methods=['POST'])
def authenticate_face():
    """Endpoint for Laptop to send the captured face frames"""
    global system_state
    
    if system_state["locker_status"] != "awaiting_face":
        return jsonify({'success': False, 'message': 'No pending RFID scan'})
        
    data = request.json
    ambient_frame = data.get('ambient_image')
    illuminated_frame = data.get('illuminated_image')
    
    pending_user = system_state.get("pending_user")
    users = load_users()
    chat_id = ""
    if pending_user and pending_user in users:
        chat_id = users[pending_user].get('telegram_chat_id', '')
    else:
        system_state["locker_status"] = "idle"
        system_state["message"] = "User data missing"
        return jsonify({'success': False, 'message': 'User data missing'})

    # 1. Turn off LED immediately
    try:
        requests.get(ESP32_LED_OFF_URL, timeout=2.0)
    except:
        pass
        
    # 2. Verify Liveness
    liveness_passed, liveness_msg, std_dev, glare_ratio = verify_blue_light(ambient_frame, illuminated_frame)
    if not liveness_passed:
        system_state["locker_status"] = "idle"
        system_state["message"] = f"Liveness Failed: {liveness_msg}"
        notify_telegram_user(chat_id, f"ALERT: Spoof Attempt! {liveness_msg}", illuminated_frame)
        log_access_attempt(pending_user, "Spoof", liveness_msg, illuminated_frame, std_dev, glare_ratio, None)
        return jsonify({'success': False, 'message': f'Liveness Failed: {liveness_msg}'})
    
    # 3. 1:1 Face Match
    try:
        image_bytes = base64.b64decode(illuminated_frame.split(',')[1])
        image = np.array(Image.open(BytesIO(image_bytes)))[:, :, ::-1].copy()
        
        face_locations = face_recognition.face_locations(image)
        if len(face_locations) == 0:
            system_state["locker_status"] = "idle"
            system_state["message"] = "No face found"
            notify_telegram_user(chat_id, "ALERT: No face found during authentication.", illuminated_frame)
            log_access_attempt(pending_user, "Failed", "No face found", illuminated_frame, std_dev, glare_ratio, None)
            return jsonify({'success': False, 'message': 'No face found'})
            
        live_encoding = face_recognition.face_encodings(image, face_locations)[0]
    except Exception as e:
        system_state["locker_status"] = "idle"
        system_state["message"] = "Recognition error"
        log_access_attempt(pending_user, "Failed", f"Error: {str(e)}", illuminated_frame, std_dev, glare_ratio, None)
        return jsonify({'success': False, 'message': str(e)})
        
    stored_encoding = np.array(users[pending_user]['avg_encoding'])
    face_distance = face_recognition.face_distance([stored_encoding], live_encoding)[0]
    tolerance = 0.48
    print("Tolerance: ", face_distance)

    if face_distance < tolerance:
        # SUCCESS! Tell ESP32 to open door
        print("Tolerance: ", face_distance)
        trigger_esp32_door_open()

        system_state["locker_status"] = "idle" # Reset for next user immediately
        system_state["message"] = f"Access Granted to {pending_user}. Unlocking..."
        notify_telegram_user(chat_id, f"Access Granted to {pending_user}. Locker unlocked.", illuminated_frame)
        log_access_attempt(pending_user, "Success", "Access Granted", illuminated_frame, std_dev, glare_ratio, face_distance)
        return jsonify({
            'success': True, 
            'message': f'Authentication successful! Welcome, {pending_user}! Unlocking...'
        })
    else:
        system_state["locker_status"] = "idle"
        system_state["message"] = "Face does not match RFID user"
        notify_telegram_user(chat_id, f"ALERT: Unauthorized face scanned with your RFID card! (Dist: {face_distance:.2f})", illuminated_frame)
        log_access_attempt(pending_user, "Failed", "Face Mismatch", illuminated_frame, std_dev, glare_ratio, face_distance)
        return jsonify({'success': False, 'message': 'Face does not match RFID user'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)