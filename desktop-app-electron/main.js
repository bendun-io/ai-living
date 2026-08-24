const { app, BrowserWindow, Menu, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

let mainWindow = null;
let debugWindow = null;
let debugState = {
  currentThreadId: null,
  threads: [],
};

const DEBUG_DOCK_GAP = 10;
const DEFAULT_DEBUG_WIDTH = 560;
let debugWindowPrefs = {
  dockToRight: true,
  width: DEFAULT_DEBUG_WIDTH,
};

function getDebugPrefsPath() {
  return path.join(app.getPath('userData'), 'debug-window-prefs.json');
}

function getThreadsPath() {
  return path.join(app.getPath('userData'), 'threads.json');
}

function loadThreadsFromDisk() {
  try {
    const raw = fs.readFileSync(getThreadsPath(), 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object' && Array.isArray(parsed.threads)) {
      return {
        threads: parsed.threads,
        currentThreadId: parsed.currentThreadId || null,
      };
    }
  } catch {
    // No saved threads yet, or file is unreadable/corrupt.
  }
  return { threads: [], currentThreadId: null };
}

function saveThreadsToDisk(data) {
  try {
    const threads = Array.isArray(data && data.threads) ? data.threads : [];
    const currentThreadId = (data && data.currentThreadId) || null;
    fs.writeFileSync(getThreadsPath(), JSON.stringify({ threads, currentThreadId }, null, 2), 'utf8');
  } catch {
    // Non-fatal: ignore persistence failures.
  }
}

function loadDebugPrefs() {
  try {
    const raw = fs.readFileSync(getDebugPrefsPath(), 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') {
      debugWindowPrefs = {
        dockToRight: parsed.dockToRight !== false,
        width: Number.isFinite(parsed.width) ? Math.max(420, Math.round(parsed.width)) : DEFAULT_DEBUG_WIDTH,
      };
    }
  } catch {
    // Ignore and keep defaults.
  }
}

function saveDebugPrefs() {
  try {
    fs.writeFileSync(getDebugPrefsPath(), JSON.stringify(debugWindowPrefs, null, 2), 'utf8');
  } catch {
    // Non-fatal: ignore persistence failures.
  }
}

function dockDebugWindowToRight() {
  if (!mainWindow || mainWindow.isDestroyed() || !debugWindow || debugWindow.isDestroyed()) {
    return;
  }
  if (!debugWindowPrefs.dockToRight) {
    return;
  }

  const mainBounds = mainWindow.getBounds();
  const targetWidth = Math.max(debugWindow.getMinimumSize()[0], debugWindowPrefs.width || DEFAULT_DEBUG_WIDTH);
  const targetHeight = Math.max(debugWindow.getMinimumSize()[1], mainBounds.height);
  const targetX = mainBounds.x + mainBounds.width + DEBUG_DOCK_GAP;
  const targetY = mainBounds.y;

  debugWindow.setBounds({
    x: targetX,
    y: targetY,
    width: targetWidth,
    height: targetHeight,
  });
}

function bindDockingHandlers() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }

  const dock = () => {
    dockDebugWindowToRight();
  };

  mainWindow.on('move', dock);
  mainWindow.on('resize', dock);
}

function sendDebugState() {
  if (debugWindow && !debugWindow.isDestroyed()) {
    debugWindow.webContents.send('debug-window-state', debugState);
  }
}

function ensureDebugWindow() {
  if (debugWindow && !debugWindow.isDestroyed()) {
    dockDebugWindowToRight();
    debugWindow.focus();
    sendDebugState();
    return debugWindow;
  }

  debugWindow = new BrowserWindow({
    width: debugWindowPrefs.width,
    height: 720,
    minWidth: 420,
    minHeight: 400,
    title: 'AI Living Debug',
    backgroundColor: '#0b1220',
    autoHideMenuBar: true,
    icon: path.join(__dirname, 'img', 'jarvis.png'),
    parent: mainWindow || undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  debugWindow.on('resize', () => {
    if (!debugWindow || debugWindow.isDestroyed()) {
      return;
    }
    const [width] = debugWindow.getSize();
    debugWindowPrefs.width = Math.max(420, width);
    saveDebugPrefs();
  });

  debugWindow.on('move', () => {
    if (!debugWindow || debugWindow.isDestroyed()) {
      return;
    }
    if (!mainWindow || mainWindow.isDestroyed()) {
      return;
    }
    const mainBounds = mainWindow.getBounds();
    const debugBounds = debugWindow.getBounds();
    const expectedX = mainBounds.x + mainBounds.width + DEBUG_DOCK_GAP;
    const expectedY = mainBounds.y;
    const isDocked = Math.abs(debugBounds.x - expectedX) <= 12 && Math.abs(debugBounds.y - expectedY) <= 12;
    debugWindowPrefs.dockToRight = isDocked;
    saveDebugPrefs();
  });

  debugWindow.on('closed', () => {
    debugWindow = null;
  });

  debugWindow.loadFile(path.join(__dirname, 'debug.html'));
  debugWindow.webContents.once('did-finish-load', () => {
    dockDebugWindowToRight();
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
    icon: path.join(__dirname, 'img', 'jarvis.png'),
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

ipcMain.handle('threads-load', () => loadThreadsFromDisk());

ipcMain.on('threads-save', (_event, data) => {
  saveThreadsToDisk(data);
});

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
  loadDebugPrefs();
  Menu.setApplicationMenu(null);
  createWindow();
  bindDockingHandlers();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
      bindDockingHandlers();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
