const backendAddress = 'http://localhost:8080';

function checkBackend() {
    const xhrIndex = new XMLHttpRequest();
    xhrIndex.onload = backendReady;
    xhrIndex.onerror = backendNotReady;
    xhrIndex.open('GET', backendAddress);
    xhrIndex.send();
}

function backendNotReady() {
    console.log('Backend is not ready.');
    setTimeout(checkBackend, 500);
}

function backendReady() {
    location.replace(backendAddress);
}

checkBackend();
