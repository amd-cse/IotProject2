let stream = null;
let capturedImages = [];
let imageCount = 0;

document.addEventListener('DOMContentLoaded', function () {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const startCameraBtn = document.getElementById('startCamera');
    const captureBtn = document.getElementById('capture');
    const captureMultipleBtn = document.getElementById('captureMultiple');
    const enrollBtn = document.querySelector('button[type="submit"]');
    const capturedImagesDiv = document.getElementById('capturedImages');
    const statusDiv = document.getElementById('status');

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

    captureBtn.addEventListener('click', function () {
        captureImage();
    });

    captureMultipleBtn.addEventListener('click', async function () {
        captureMultipleBtn.disabled = true;
        captureBtn.disabled = true;

        for (let i = 0; i < 5; i++) {
            await new Promise(resolve => setTimeout(resolve, 1000));
            captureImage();
            showStatus(`Capturing image ${i + 1} of 5...`, 'info');
        }

        captureMultipleBtn.disabled = false;
        captureBtn.disabled = false;
        showStatus('All 5 images captured!', 'success');
    });

    function captureImage() {
        const context = canvas.getContext('2d');
        context.drawImage(video, 0, 0, 640, 480);

        const imageData = canvas.toDataURL('image/jpeg');
        capturedImages.push(imageData);
        imageCount++;

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

        if (capturedImages.length >= 3) {
            enrollBtn.disabled = false;
        }
    }

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
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: userName,
                    images: capturedImages
                })
            });

            const result = await response.json();

            if (result.success) {
                showStatus(result.message, 'success');
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

    function showStatus(message, type) {
        statusDiv.innerHTML = `<div class="alert alert-${type}" role="alert">${message}</div>`;
        if (type === 'success') {
            setTimeout(() => { statusDiv.innerHTML = ''; }, 5000);
        }
    }
});