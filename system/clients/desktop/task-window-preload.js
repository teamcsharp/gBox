'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('taskWindow', {
  info: () => ipcRenderer.invoke('task-window:info'),
  api: path => ipcRenderer.invoke('task-window:api', { path, method: 'GET' }),
  image: digest => ipcRenderer.invoke('task-window:image', digest),
  alwaysOnTop: on => ipcRenderer.invoke('task-window:top', on),
  onScope: fn => {
    const listener = (_event, value) => fn(value);
    ipcRenderer.on('task-window:scope', listener);
    return () => ipcRenderer.removeListener('task-window:scope', listener);
  }
});
