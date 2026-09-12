import { contextBridge, ipcRenderer } from "electron";

/**
 * Bridge for the first-run config wizard (loaded from file://, before the local service starts).
 * The renderer submits a plain config object; main writes config.json +
 * desktop-env.json and closes the wizard.
 */
contextBridge.exposeInMainWorld("nanobotWizard", {
  submit: (data: unknown) => ipcRenderer.invoke("desktop:submit-wizard-config", data),
  pickFile: () => ipcRenderer.invoke("desktop:wizard-pick-file"),
  pickFolder: () => ipcRenderer.invoke("desktop:wizard-pick-folder"),
});
