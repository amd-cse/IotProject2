import os
import json
import math
import random
import base64
import numpy as np
import cv2
import face_recognition
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from PIL import Image
from io import BytesIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this'

# Database file path
USERS_DB = 'data/users.json'

# Ensure data directory exists
os.makedirs('data', exist_ok=True)

# Initialize database if it doesn't exist
if not os.path.exists(USERS_DB):
    with open(USERS_DB, 'w') as f:
        json.dump({}, f)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def load_users():
    """Load all users from the JSON database"""
    try:
        with open(USERS_DB, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    """Save users dictionary to the JSON database"""
    with open(USERS_DB, 'w') as f:
        json.dump(users, f, indent=2)

def calculate_distance(p1, p2):
    """Calculate Euclidean distance between two points"""
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def get_center(points):
    """Get the centroid of a list of (x,y) points"""
    x = sum(p[0] for p in points) / len(points)
    y = sum(p[1] for p in points) / len(points)
    return (x, y)

def get_face_encoding_from_image(image_array):
    """Extract face encoding from a NumPy BGR image array"""
    face_locations = face_recognition.face_locations(image_array)
    if len(face_locations) == 0:
        return None, "No face detected"
    
    # Take the first face found
    encodings = face_recognition.face_encodings(image_array, face_locations)
    if len(encodings) == 0:
        return None, "Could not extract encoding"
        
    return encodings[0], "Success"

def check_action(landmarks_list, challenge):
    """Verify if the requested liveness action occurred across the 3 frames"""
    if len(landmarks_list) < 3:
        return False, "Not enough frames captured"
    
    frame1 = landmarks_list[0] # Resting state
    frame3 = landmarks_list[2] # Peak action state
    
    try:
        # 1. BLINK CHECK (Eye Aspect Ratio - EAR)
        if challenge == 'blink':
            def get_ear(eye_landmarks):
                # Vertical distances
                A = calculate_distance(eye_landmarks[1], eye_landmarks[5])
                B = calculate_distance(eye_landmarks[2], eye_landmarks[4])
                # Horizontal distance
                C = calculate_distance(eye_landmarks[0], eye_landmarks[3])
                return (A + B) / (2.0 * C)
            
            ear1 = (get_ear(frame1['left_eye']) + get_ear(frame1['right_eye'])) / 2.0
            ear3 = (get_ear(frame3['left_eye']) + get_ear(frame3['right_eye'])) / 2.0
            
            # Eyes closed are roughly 30% smaller than open
            if ear3 < ear1 * 0.7: 
                return True, "Blink detected"
            return False, "No blink detected"

        # 2. SMILE CHECK (Mouth Aspect Ratio - MAR)
        elif challenge == 'smile':
            def get_mar(top_lip, bottom_lip):
                # Width of mouth (corners)
                width = calculate_distance(top_lip[0], top_lip[-1])
                # Height of mouth
                height = calculate_distance(get_center(top_lip), get_center(bottom_lip))
                return width / (height + 1e-6) # Prevent division by zero
            
            mar1 = get_mar(frame1['top_lip'], frame1['bottom_lip'])
            mar3 = get_mar(frame3['top_lip'], frame3['bottom_lip'])
            
            # Mouth gets wider relative to height when smiling
            if mar3 > mar1 * 1.3: 
                return True, "Smile detected"
            return False, "No smile detected"

        # 3. HEAD TURN CHECK (Nose to Eye distance ratio)
        elif challenge in ['turn_left', 'turn_right']:
            def get_turn_ratio(landmarks):
                nose_tip = get_center(landmarks['nose_tip'])
                left_eye = get_center(landmarks['left_eye'])
                right_eye = get_center(landmarks['right_eye'])
                
                dist_left = calculate_distance(nose_tip, left_eye)
                dist_right = calculate_distance(nose_tip, right_eye)
                
                return dist_left / (dist_right + 1e-6)
            
            ratio1 = get_turn_ratio(frame1)
            ratio3 = get_turn_ratio(frame3)
            
            if challenge == 'turn_left':
                # Turning left makes nose closer to right eye (ratio increases)
                if ratio3 > ratio1 * 1.3:
                    return True, "Left turn detected"
            else: # turn_right
                # Turning right makes nose closer to left eye (ratio decreases)
                if ratio3 < ratio1 * 0.7:
                    return True, "Right turn detected"
            
            return False, "Head turn not detected"

        return False, "Unknown challenge"
        
    except Exception as e:
        return False, f"Error checking action: {str(e)}"

# ==========================================
# FLASK ROUTES
# ==========================================

@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@app.route('/enroll', methods=['GET', 'POST'])
def enroll():
    """User enrollment page - captures multiple images for robust encoding"""
    if request.method == 'POST':
        data = request.json
        name = data.get('name')
        images = data.get('images', [])
        
        if not name or not images:
            return jsonify({'success': False, 'message': 'Name and images are required'})
        
        # Check if user already exists
        users = load_users()
        if name in users:
            return jsonify({'success': False, 'message': 'User already exists'})
        
        # Process each image to extract encodings
        encodings = []
        
        for img_data in images:
            try:
                # Decode base64 image
                image_bytes = base64.b64decode(img_data.split(',')[1])
                image = Image.open(BytesIO(image_bytes))
                image_array = np.array(image)
                
                # Convert RGB to BGR (for face_recognition library)
                image_array = image_array[:, :, ::-1].copy()
                
                encoding, enc_msg = get_face_encoding_from_image(image_array)
                if encoding is not None:
                    encodings.append(encoding.tolist())
                    
            except Exception as e:
                continue
        
        if len(encodings) < 3:
            return jsonify({'success': False, 'message': 'Need at least 3 good quality images with clear face'})
        
        # Store user with average encoding
        avg_encoding = np.mean(encodings, axis=0).tolist()
        users[name] = {
            'encodings': encodings,
            'avg_encoding': avg_encoding,
            'enrollment_date': datetime.now().isoformat(),
            'image_count': len(encodings)
        }
        
        save_users(users)
        
        return jsonify({
            'success': True, 
            'message': f'User {name} enrolled successfully with {len(encodings)} images',
            'encoding_count': len(encodings)
        })
    
    return render_template('enroll.html')

@app.route('/get_liveness_challenge', methods=['GET'])
def get_liveness_challenge():
    """Generate a random liveness challenge for the user"""
    challenges = ['blink', 'smile', 'turn_left', 'turn_right']
    challenge = random.choice(challenges)
    return jsonify({'challenge': challenge})

@app.route('/authenticate', methods=['GET', 'POST'])
def authenticate():
    """User authentication with active multi-frame liveness detection"""
    if request.method == 'POST':
        data = request.json
        images = data.get('images', [])  # Expecting exactly 3 frames
        challenge = data.get('challenge')
        
        if not images or len(images) < 3 or not challenge:
            return jsonify({'success': False, 'message': 'Missing frames or challenge data'})
        
        # Process frames to get landmarks and encodings
        landmarks_list = []
        face_encodings = []
        
        for img_data in images:
            try:
                # Decode base64 image
                image_bytes = base64.b64decode(img_data.split(',')[1])
                image = Image.open(BytesIO(image_bytes))
                image_array = np.array(image)
                
                # Convert RGB to BGR
                image_array = image_array[:, :, ::-1].copy()
                
                face_locations = face_recognition.face_locations(image_array)
                if len(face_locations) == 0:
                    continue
                
                # Take the first face found
                landmarks = face_recognition.face_landmarks(image_array, face_locations)[0]
                encodings = face_recognition.face_encodings(image_array, face_locations)
                
                landmarks_list.append(landmarks)
                if encodings:
                    face_encodings.append(encodings[0])
                    
            except Exception as e:
                continue
        
        if len(landmarks_list) < 3 or len(face_encodings) < 3:
            return jsonify({'success': False, 'message': 'Could not detect face consistently in all frames'})
        
        # 1. Verify Liveness Action
        action_passed, action_msg = check_action(landmarks_list, challenge)
        if not action_passed:
            return jsonify({'success': False, 'message': f'Liveness Failed: {action_msg}'})
        
        # 2. Face Recognition (Use the middle frame as the "peak" action face)
        live_encoding = face_encodings[1] # Middle frame
        
        users = load_users()
        if not users:
            return jsonify({'success': False, 'message': 'No users enrolled in the system'})
        
        best_match = None
        best_distance = 1.0  # Lower is better
        tolerance = 0.6      # Default tolerance for face_recognition
        
        for name, user_data in users.items():
            stored_encoding = np.array(user_data['avg_encoding'])
            
            # Calculate face distance
            face_distance = face_recognition.face_distance([stored_encoding], live_encoding)[0]
            
            if face_distance < best_distance:
                best_distance = face_distance
                best_match = name
            
        # Check if we have a match within tolerance
        if best_distance < tolerance:
            return jsonify({
                'success': True,
                'message': f'Authentication successful! Welcome, {best_match}!',
                'user': best_match,
                'confidence': 1 - best_distance
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Authentication failed. Face not recognized.',
                'best_distance': float(best_distance),
                'tolerance': tolerance
            })
    
    return render_template('authenticate.html')

@app.route('/users')
def list_users():
    """List all enrolled users"""
    users = load_users()
    user_list = []
    for name, data in users.items():
        user_list.append({
            'name': name,
            'enrollment_date': data.get('enrollment_date'),
            'image_count': data.get('image_count')
        })
    return jsonify({'users': user_list})

if __name__ == '__main__':
    # Host 0.0.0.0 makes it accessible on your local network (e.g., from a phone)
    app.run(debug=True, host='0.0.0.0', port=5000)