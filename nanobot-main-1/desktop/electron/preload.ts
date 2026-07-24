import { contextBridge, ipcRenderer } from "electron";

/**
 * Minimal, deliberately narrow bridge exposed to the renderer as
 * ``window.nanobotDesktop``. contextIsolation stays on and nodeIntegration off;
 * the WebUI never gets direct Node/Electron capabilities, only these IPC calls.
 */
contextBridge.exposeInMainWorld("nanobotDesktop", {
  openConfigDir: () => ipcRenderer.invoke("desktop:open-config-dir"),
  openLogs: () => ipcRenderer.invoke("desktop:open-logs"),
  getAppInfo: () => ipcRenderer.invoke("desktop:get-app-info"),
  restartRobotServer: () => ipcRenderer.invoke("desktop:restart-robot-server"),
});
