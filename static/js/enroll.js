let stream = null;
let capturedImages = [];
let imageCount = 0;

document.addEventListener('DOMContentLoaded', function () {
    // Elements
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const startCameraBtn = document.getElementById('startCamera');
    const captureBtn = document.getElementById('capture');
    const captureMultipleBtn = document.getElementById('captureMultiple');
    const enrollBtn = document.querySelector('button[type="submit"]');
    const capturedImagesDiv = document.getElementById('capturedImages');
    const statusDiv = document.getElementById('status');

    // Start camera
    startCameraBtn.addEventListener('click', async function () {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            video.srcObject = stream;
            captureBtn.disabled = false;
            captureMultipleBtn.disabled = false;
            startCameraBtn.disabled = true;
            showStatus('Camera started successfully', 'success');
        } catch (err) {
            showStatus('Error accessing camera: ' + err.message, 'danger');
        }
    });

    // Capture single image
    captureBtn.addEventListener('click', function () {
        captureImage();
    });

    // Capture multiple images
    captureMultipleBtn.addEventListener('click', async function () {
        captureMultipleBtn.disabled = true;
        captureBtn.disabled = true;

        for (let i = 0; i < 5; i++) {
            await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second
            captureImage();
            showStatus(`Capturing image ${i + 1} of 5...`, 'info');
        }

        captureMultipleBtn.disabled = false;
        captureBtn.disabled = false;
        showStatus('All 5 images captured!', 'success');
    });

    // Capture image function
    function captureImage() {
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, 640, 480);

        const imageData = canvas.toDataURL('image/jpeg');
        capturedImages.push(imageData);
        imageCount++;

        // Add to preview
        const imgDiv = document.createElement('div');
        imgDiv.className = 'col-md-2 mb-2';
        imgDiv.innerHTML = `
            <div class="card">
                <img src="${imageData}" class="card-img-top" alt="Captured ${imageCount}">
                <div class="card-body p-2">
                    <small class="text-muted">Image ${imageCount}</small>
                </div>
            </div>
        `;
        capturedImagesDiv.appendChild(imgDiv);

        // Enable enroll button if we have enough images
        if (capturedImages.length >= 3) {
            enrollBtn.disabled = false;
        }
    }

    // Form submission
    document.getElementById('enrollmentForm').addEventListener('submit', async function (e) {
        e.preventDefault();

        const userName = document.getElementById('userName').value;

        if (!userName) {
            showStatus('Please enter a user name', 'danger');
            return;
        }

        if (capturedImages.length < 3) {
            showStatus('Please capture at least 3 images', 'danger');
            return;
        }

        enrollBtn.disabled = true;
        showStatus('Enrolling user... Please wait.', 'info');

        try {
            const response = await fetch('/enroll', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    name: userName,
                    images: capturedImages
                })
            });

            const result = await response.json();

            if (result.success) {
                showStatus(result.message, 'success');
                // Reset form
                document.getElementById('enrollmentForm').reset();
                capturedImages = [];
                imageCount = 0;
                capturedImagesDiv.innerHTML = '';
                enrollBtn.disabled = true;
            } else {
                showStatus(result.message, 'danger');
                enrollBtn.disabled = false;
            }
        } catch (err) {
            showStatus('Error: ' + err.message, 'danger');
            enrollBtn.disabled = false;
        }
    });

    // Show status function
    function showStatus(message, type) {
        statusDiv.innerHTML = `
            <div class="alert alert-${type}" role="alert">
                ${message}
            </div>
        `;

        // Auto-hide success messages after 5 seconds
        if (type === 'success') {
            setTimeout(() => {
                statusDiv.innerHTML = '';
            }, 5000);
        }
    }
});