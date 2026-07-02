// static/js/locker.js

let stream = null;
let polling = true;
let isProcessingLiveness = false; // Prevents double-triggering

// Initialize DOM elements
const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const statusText = document.getElementById('statusText');

// Initialize camera immediately on page load so it's ready when RFID is scanned
async function initCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ video: true });
        video.srcObject = stream;
        video.style.display = "none"; // Keep hidden until an RFID scan occurs
    } catch (err) {
        if (statusText) {
            statusText.innerText = "Camera Error: " + err.message;
            statusText.style.color = "red";
        }
        console.error("Camera access error:", err);
    }
}

// Start the camera when the script loads
window.onload = initCamera;

// Poll the Flask backend for locker status
async function checkStatus() {
    if (!polling || isProcessingLiveness) return;

    try {
        const res = await fetch('/api/locker/status');
        const data = await res.json();

        // Update UI message
        if (statusText) {
            statusText.innerText = data.message;
            // Color code the status text
            if (data.locker_status === 'idle') statusText.style.color = '#6c757d'; // Gray
            else if (data.locker_status === 'awaiting_face') statusText.style.color = '#0d6efd'; // Blue
            else if (data.locker_status === 'unlock') statusText.style.color = '#198754'; // Green
        }

        // If an RFID was scanned, trigger the face liveness sequence
        // FIX: Changed data.status to data.locker_status
        if (data.locker_status === 'awaiting_face') {
            isProcessingLiveness = true; // Lock the sequence
            polling = false; // Stop polling while we capture and process

            if (video) video.style.display = "block";
            if (statusText) statusText.innerText = "Scanning face... Please look at the camera.";

            try {
                await triggerLivenessCheck();
            } catch (error) {
                console.error("Liveness sequence error:", error);
                if (statusText) statusText.innerText = "Error: " + error.message;
            } finally {
                // Resume polling after sequence is complete or fails
                isProcessingLiveness = false;
                polling = true;
            }
        } else if (data.locker_status === 'idle' || data.locker_status === 'unlock') {
            // Hide video when system is idle or unlocking
            if (video) video.style.display = "none";
        }
    } catch (e) {
        console.error("Polling error:", e);
        // If the server is down, wait a bit before trying again
        await new Promise(r => setTimeout(r, 2000));
    }
}

// Orchestrate the Blue LED liveness check
async function triggerLivenessCheck() {
    if (!stream || !video || !canvas) {
        throw new Error("Camera not initialized properly.");
    }

    const context = canvas.getContext('2d');

    // 1. Capture Ambient Frame (LED is currently OFF)
    context.drawImage(video, 0, 0, 640, 480);
    const ambientFrame = canvas.toDataURL('image/jpeg');

    // 2. Tell Flask to turn ON the ESP32 Blue LED
    if (statusText) statusText.innerText = "Activating Blue LEDs...";
    const ledRes = await fetch('/liveness/start', { method: 'POST' });
    const ledData = await ledRes.json();

    if (!ledData.success) {
        throw new Error(ledData.message || "Failed to communicate with ESP32 LED");
    }

    // Wait 500ms for LED to physically turn on and webcam exposure to adjust
    await new Promise(r => setTimeout(r, 500));

    // 3. Capture Illuminated Frame (LED is ON)
    if (statusText) statusText.innerText = "Capturing illuminated frame...";
    context.drawImage(video, 0, 0, 640, 480);
    const illuminatedFrame = canvas.toDataURL('image/jpeg');

    // 4. Send both frames to Flask for verification
    if (statusText) statusText.innerText = "Verifying identity...";
    const response = await fetch('/api/authenticate_face', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            ambient_image: ambientFrame,
            illuminated_image: illuminatedFrame
        })
    });

    const result = await response.json();
    console.log("Authentication response:", result);

    // The UI status will update automatically via polling in the next tick.
}

// Start polling the server every 1 second
setInterval(checkStatus, 1000);