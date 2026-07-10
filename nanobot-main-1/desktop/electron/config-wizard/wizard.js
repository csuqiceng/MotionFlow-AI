// First-run config wizard renderer. Talks to main only through the
// window.nanobotWizard bridge (see wizard-preload.ts); no direct Node access.
"use strict";

const DEFAULT_BASE = {
  custom: "",
  openai: "",
  zhipu: "https://open.bigmodel.cn/api/coding/paas/v4",
  deepseek: "https://api.deepseek.com",
  gemini: "",
  anthropic: "",
};

const $ = (id) => document.getElementById(id);
const providerSel = $("provider");
const apiBase = $("apiBase");

providerSel.addEventListener("change", () => {
  const d = DEFAULT_BASE[providerSel.value];
  if (d !== undefined) apiBase.value = d;
});
apiBase.value = DEFAULT_BASE[providerSel.value] ?? "";

$("pickWrapper").addEventListener("click", async () => {
  const p = await window.nanobotWizard.pickFile();
  if (p) $("dllWrapper").value = p;
});
$("pickDllDir").addEventListener("click", async () => {
  const p = await window.nanobotWizard.pickFolder();
  if (p) $("dllDir").value = p;
});

$("save").addEventListener("click", async () => {
  const err = $("err");
  err.textContent = "";
  const provider = providerSel.value;
  const apiKey = $("apiKey").value.trim();
  const model = $("model").value.trim();
  if (!apiKey) { err.textContent = "请填写 API Key"; return; }
  if (!model) { err.textContent = "请填写模型名称"; return; }

  const data = {
    provider,
    apiKey,
    apiBase: apiBase.value.trim(),
    model,
    controllerHost: $("controllerHost").value.trim(),
    backendMode: $("backendMode").value,
    dllWrapper: $("dllWrapper").value.trim(),
    dllDir: $("dllDir").value.trim(),
  };
  $("save").disabled = true;
  try {
    const res = await window.nanobotWizard.submit(data);
    if (!res || !res.ok) {
      err.textContent = (res && res.error) || "保存失败";
      $("save").disabled = false;
    }
    // on success, main closes this window and proceeds to bootstrap
  } catch (e) {
    err.textContent = String(e);
    $("save").disabled = false;
  }
});
