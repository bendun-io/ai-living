const { app, BrowserWindow, Menu, ipcMain } = require('electron');
const path = require('path');

let mainWindow = null;
let debugWindow = null;
let debugState = {
  currentThreadId: null,
  threads: [],
};

function sendDebugState() {
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.webContents.send('debug-window-state', debugState);
  }
}

function ensureDebugWindow() {
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.focus();
    sendDebugState();
    return debugWindow;
  }

  debugWindow = new BrowserWindow({
    width: 560,
    height: 720,
    minWidth: 420,
    minHeight: 400,
    title: 'AI Living Debug',
    backgroundColor: '#0b1220',
    autoHideMenuBar: true,
    parent: mainWindow || undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  debugWindow.on('closed', () => {
    debugWindow = null;
  });

  debugWindow.loadFile(path.join(__dirname, 'debug.html'));
  debugWindow.webContents.once('did-finish-load', () => {
    sendDebugState();
  });
  return debugWindow;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#0f172a',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

ipcMain.handle('debug-window-open', () => {
  ensureDebugWindow();
});

ipcMain.handle('debug-window-get-state', () => debugState);

ipcMain.on('debug-window-update', (_event, state) => {
  if (state && typeof state === 'object') {
    debugState = {
      currentThreadId: state.currentThreadId || null,
      threads: Array.isArray(state.threads) ? state.threads : [],
    };
    sendDebugState();
  }
});

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
