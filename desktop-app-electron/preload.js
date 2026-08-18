const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('appInfo', {
  appName: 'AI Living Electron',
  version: '0.1.0',
});
