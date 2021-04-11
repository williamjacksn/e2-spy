const { app, BrowserWindow } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');

function initialize_dirs() {
    const orig_app_data_dir = app.getPath('appData');
    const app_data_dir = path.join(path.dirname(orig_app_data_dir), 'Local');
    app.setPath('appData', app_data_dir);
    const user_data_dir = path.join(app_data_dir, 'William Jackson/E2 Spy');
    app.setPath('userData', user_data_dir);
    app.setAppLogsPath(path.join(user_data_dir, 'Logs'))
}

initialize_dirs();

if (require('electron-squirrel-startup')) return;

let backend;

function createWindow() {
    // launch backend app
    const python_exe = path.join(__dirname, 'backend/python.exe');
    const backend_app = path.join(__dirname, 'backend/backend/app.py');
    backend = spawn(python_exe, ['-u', backend_app]);

    // launch frontend
    const win = new BrowserWindow({
        autoHideMenuBar: true,
        show: false
    });

    win.loadFile('pre-index.html');
    win.maximize();
    win.show();
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
    execSync(`taskkill /pid ${backend.pid} /t /f`);
    app.quit();
});
