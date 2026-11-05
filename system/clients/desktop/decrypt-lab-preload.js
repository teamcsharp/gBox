'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('decryptLab', {
  info: () => ipcRenderer.invoke('decrypt-lab:info'),
  api: (path, body, method) => ipcRenderer.invoke('decrypt-lab:api', { path, body, method }),
  preview: (title, path) => ipcRenderer.invoke('decrypt-lab:preview', { title, path }),
  alwaysOnTop: (on) => ipcRenderer.invoke('decrypt-lab:top', on),
  onScope: (fn) => {
    const listener = (_event, value) => fn(value);
    ipcRenderer.on('decrypt-lab:scope', listener);
    return () => ipcRenderer.removeListener('decrypt-lab:scope', listener);
  },
});
