import os
import json
import base64
import numpy as np
import cv2
import face_recognition
import requests
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from PIL import Image
from io import BytesIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this'

USERS_DB = 'data/users.json'
os.makedirs('data', exist_ok=True)
if not os.path.exists(USERS_DB):
    with open(USERS_DB, 'w') as f:
        json.dump({}, f)

# --- ESP32 Configuration ---
ESP32_IP = "192.168.137.238"  # Replace with your ESP32 IP
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

def verify_blue_light(ambient_frame_data, illuminated_frame_data):
    try:
        ambient_bytes = base64.b64decode(ambient_frame_data.split(',')[1])
        ambient_img = np.array(Image.open(BytesIO(ambient_bytes)))[:, :, ::-1].copy()
        
        illuminated_bytes = base64.b64decode(illuminated_frame_data.split(',')[1])
        illuminated_img = np.array(Image.open(BytesIO(illuminated_bytes)))[:, :, ::-1].copy()
        
        face_locations = face_recognition.face_locations(illuminated_img)
        if len(face_locations) == 0:
            return False, "No face detected during liveness check"
        
        top, right, bottom, left = face_locations[0]
        ambient_face = ambient_img[top:bottom, left:right]
        illuminated_face = illuminated_img[top:bottom, left:right]
        
        ambient_ratio = calculate_blue_ratio(ambient_face)
        illuminated_ratio = calculate_blue_ratio(illuminated_face)
        
        if illuminated_ratio > 0.05 and illuminated_ratio > ambient_ratio * 2.0:
            return True, "Liveness verified"
        else:
            return False, "Blue light change not detected"
    except Exception as e:
        return False, f"Error: {str(e)}"

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
def enroll():
    global system_state
    if request.method == 'POST':
        data = request.json
        name = data.get('name')
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
def enrollment_scan_rfid():
    """Called by browser to check if ESP32 has an RFID UID during enrollment"""
    if system_state["mode"] != "enrolling":
        return jsonify({'success': False, 'message': 'Not in enrollment mode'})
    
    uid = pop_esp32_rfid()
    if uid:
        return jsonify({'success': True, 'uid': uid})
    return jsonify({'success': False})

@app.route('/api/enrollment/cancel', methods=['POST'])
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
    global system_state
    system_state["mode"] = "auth"
    system_state["locker_status"] = "idle"
    system_state["message"] = "System Idle. Scan RFID to begin."
    return render_template('locker.html')

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
    
    # 1. Turn off LED immediately
    try:
        requests.get(ESP32_LED_OFF_URL, timeout=2.0)
    except:
        pass
        
    # 2. Verify Liveness
    liveness_passed, liveness_msg = verify_blue_light(ambient_frame, illuminated_frame)
    if not liveness_passed:
        system_state["locker_status"] = "idle"
        system_state["message"] = f"Liveness Failed: {liveness_msg}"
        return jsonify({'success': False, 'message': f'Liveness Failed: {liveness_msg}'})
    
    # 3. 1:1 Face Match
    try:
        image_bytes = base64.b64decode(illuminated_frame.split(',')[1])
        image = np.array(Image.open(BytesIO(image_bytes)))[:, :, ::-1].copy()
        
        face_locations = face_recognition.face_locations(image)
        if len(face_locations) == 0:
            system_state["locker_status"] = "idle"
            system_state["message"] = "No face found"
            return jsonify({'success': False, 'message': 'No face found'})
            
        live_encoding = face_recognition.face_encodings(image, face_locations)[0]
    except Exception as e:
        system_state["locker_status"] = "idle"
        system_state["message"] = "Recognition error"
        return jsonify({'success': False, 'message': str(e)})
        
    pending_user = system_state["pending_user"]
    users = load_users()
    
    if pending_user not in users:
        system_state["locker_status"] = "idle"
        system_state["message"] = "User data missing"
        return jsonify({'success': False, 'message': 'User data missing'})
        
    stored_encoding = np.array(users[pending_user]['avg_encoding'])
    face_distance = face_recognition.face_distance([stored_encoding], live_encoding)[0]
    tolerance = 0.6
    
    if face_distance < tolerance:
        # SUCCESS! Tell ESP32 to open door
        trigger_esp32_door_open()
        system_state["locker_status"] = "idle" # Reset for next user immediately
        system_state["message"] = f"Access Granted to {pending_user}. Unlocking..."
        return jsonify({
            'success': True, 
            'message': f'Authentication successful! Welcome, {pending_user}! Unlocking...'
        })
    else:
        system_state["locker_status"] = "idle"
        system_state["message"] = "Face does not match RFID user"
        return jsonify({'success': False, 'message': 'Face does not match RFID user'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)