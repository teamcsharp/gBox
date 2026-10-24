'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('mercsWindow',{
  info:()=>ipcRenderer.invoke('mercs-window:info'),
  api:(path,body,method)=>ipcRenderer.invoke('mercs-window:api',{path,body,method}),
  alwaysOnTop:on=>ipcRenderer.invoke('mercs-window:top',on),
  onScope:fn=>{const listener=(_event,value)=>fn(value);ipcRenderer.on('mercs-window:scope',listener);
    return ()=>ipcRenderer.removeListener('mercs-window:scope',listener);}
});
