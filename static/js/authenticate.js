let stream = null;

document.addEventListener('DOMContentLoaded', function () {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const startCameraBtn = document.getElementById('startCamera');
    const startAuthBtn = document.getElementById('startAuth');
    const resultDiv = document.getElementById('result');
    const challengePrompt = document.getElementById('challengePrompt');
    const overlay = document.getElementById('overlay');

    // Start camera
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

    // Start Authentication Flow
    startAuthBtn.addEventListener('click', async function () {
        startAuthBtn.disabled = true;
        resultDiv.innerHTML = '';

        try {
            // 1. Get Challenge from Backend
            const challengeRes = await fetch('/get_liveness_challenge');
            const challengeData = await challengeRes.json();
            const challenge = challengeData.challenge;

            // 2. Display Challenge to User
            let challengeText = '';
            let overlayText = '';

            if (challenge === 'blink') {
                challengeText = 'Please BLINK your eyes clearly';
                overlayText = 'BLINK';
            } else if (challenge === 'smile') {
                challengeText = 'Please SMILE clearly';
                overlayText = 'SMILE';
            } else if (challenge === 'turn_left') {
                challengeText = 'Please turn your head LEFT';
                overlayText = 'TURN LEFT';
            } else if (challenge === 'turn_right') {
                challengeText = 'Please turn your head RIGHT';
                overlayText = 'TURN RIGHT';
            }

            challengePrompt.style.display = 'block';
            challengePrompt.innerHTML = `🚨 Action Required: <br>${challengeText}`;

            // Countdown 3..2..1
            await countdown(3);

            // Show overlay text
            overlay.textContent = overlayText;
            overlay.style.display = 'block';
            challengePrompt.innerHTML = 'Capturing... Please perform the action!';

            // 3. Capture 3 frames over 1.5 seconds
            const capturedFrames = [];
            for (let i = 0; i < 3; i++) {
                const context = canvas.getContext('2d');
                context.drawImage(video, 0, 0, 640, 480);
                capturedFrames.push(canvas.toDataURL('image/jpeg'));
                await new Promise(resolve => setTimeout(resolve, 500)); // 500ms delay
            }

            overlay.style.display = 'none';
            challengePrompt.style.display = 'none';

            showResult('Processing liveness detection...', 'info');

            // 4. Send to Backend
            const response = await fetch('/authenticate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    images: capturedFrames,
                    challenge: challenge
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

        startAuthBtn.disabled = false;
    });

    // Helper: Countdown timer
    function countdown(seconds) {
        return new Promise((resolve) => {
            let count = seconds;
            challengePrompt.innerHTML = `Get Ready... <br><span style="font-size: 3rem;">${count}</span>`;
            const interval = setInterval(() => {
                count--;
                if (count > 0) {
                    challengePrompt.innerHTML = `Get Ready... <br><span style="font-size: 3rem;">${count}</span>`;
                } else {
                    clearInterval(interval);
                    resolve();
                }
            }, 1000);
        });
    }

    // Helper: Show result
    function showResult(message, type) {
        resultDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
    }
});