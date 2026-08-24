const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('appInfo', {
  appName: 'AI Living Electron',
  version: '0.1.0',
});

contextBridge.exposeInMainWorld('threadsBridge', {
  load: () => ipcRenderer.invoke('threads-load'),
  save: (data) => ipcRenderer.send('threads-save', data),
});

contextBridge.exposeInMainWorld('debugBridge', {
  openDebugWindow: () => ipcRenderer.invoke('debug-window-open'),
  updateDebugState: (state) => ipcRenderer.send('debug-window-update', state),
  getDebugState: () => ipcRenderer.invoke('debug-window-get-state'),
  onDebugState: (callback) => {
    const listener = (_event, state) => callback(state);
    ipcRenderer.on('debug-window-state', listener);
    return () => ipcRenderer.removeListener('debug-window-state', listener);
  },
});
