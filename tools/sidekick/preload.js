const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('sk', {
  init: () => ipcRenderer.invoke('init'),
  setPrefs: p => ipcRenderer.invoke('set-prefs', p),
  capture: mode => ipcRenderer.invoke('capture', mode),
  record: (note, opts) => ipcRenderer.invoke('record', note, opts),
  stepRecord: i => ipcRenderer.invoke('step-record', i),
  stepDone: (i, done) => ipcRenderer.invoke('step-done', i, done),
  stepsClear: () => ipcRenderer.invoke('steps-clear'),
  saveImage: dataUrl => ipcRenderer.invoke('save-image', dataUrl),
  ask: msg => ipcRenderer.invoke('ask', msg),
  command: line => ipcRenderer.invoke('command', line),
  stop: () => ipcRenderer.invoke('stop'),
  newSession: () => ipcRenderer.invoke('new-session'),
  openFolder: () => ipcRenderer.invoke('open-folder'),
  openPermissions: () => ipcRenderer.invoke('open-permissions'),
  copy: t => ipcRenderer.invoke('copy', t),
  callout: (action, id, arg) => ipcRenderer.invoke('callout', action, id, arg),
  window: (action, arg) => ipcRenderer.invoke('window', action, arg),
  on: (ch, fn) => ipcRenderer.on(ch, (_, d) => fn(d)),
});
