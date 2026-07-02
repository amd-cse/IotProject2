let stream = null;

document.addEventListener('DOMContentLoaded', function () {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const startCameraBtn = document.getElementById('startCamera');
    const startAuthBtn = document.getElementById('startAuth');
    const resultDiv = document.getElementById('result');
    const statusDiv = document.getElementById('challengePrompt');

    startCameraBtn.addEventListener('click', async function () {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = stream;
            startAuthBtn.disabled = false;
            startCameraBtn.disabled = true;
            showResult('Camera started. Click "Start Authentication" to begin.', 'info');
        } catch (err) {
            showResult('Error accessing camera: ' + err.message, 'danger');
        }
    });

    startAuthBtn.addEventListener('click', async function () {
        startAuthBtn.disabled = true;
        resultDiv.innerHTML = '';
        statusDiv.style.display = 'block';

        try {
            // 1. Capture Ambient Frame (LED is OFF)
            statusDiv.innerHTML = "Step 1: Capturing ambient light...";
            let context = canvas.getContext('2d');
            context.drawImage(video, 0, 0, 640, 480);
            const ambientFrame = canvas.toDataURL('image/jpeg');

            // 2. Tell Backend to turn ON ESP32 LED
            statusDiv.innerHTML = "Step 2: Activating Blue LEDs...";
            const startRes = await fetch('/liveness/start', { method: 'POST' });
            const startData = await startRes.json();

            if (!startData.success) {
                throw new Error(startData.message);
            }

            // Wait 500ms for LED to physically turn on and camera exposure to adjust
            await new Promise(resolve => setTimeout(resolve, 500));

            // 3. Capture Illuminated Frame (LED is ON)
            statusDiv.innerHTML = "Step 3: Capturing illuminated frame...";
            context.drawImage(video, 0, 0, 640, 480);
            const illuminatedFrame = canvas.toDataURL('image/jpeg');

            // 4. Send both frames to Backend for verification
            statusDiv.innerHTML = "Step 4: Verifying liveness & identity...";
            const response = await fetch('/authenticate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ambient_image: ambientFrame,
                    illuminated_image: illuminatedFrame
                })
            });

            const result = await response.json();

            if (result.success) {
                showResult(`
                    <h4 class="alert-heading">✅ Authentication Successful!</h4>
                    <p>Welcome, <strong>${result.user}</strong>!</p>
                    <hr>
                    <p class="mb-0">Confidence: ${(result.confidence * 100).toFixed(2)}%</p>
                `, 'success');
            } else {
                showResult(`
                    <h4 class="alert-heading">❌ Authentication Failed</h4>
                    <p>${result.message}</p>
                `, 'danger');
            }

        } catch (err) {
            showResult('Error: ' + err.message, 'danger');
        }

        statusDiv.style.display = 'none';
        startAuthBtn.disabled = false;
    });

    function showResult(message, type) {
        resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
    }
});