; Keep the assisted installer directory page, but skip the install-scope page.
; electron-builder's multi-user UI calls this hook before rendering that page.
!macro customInstallMode
  StrCpy $isForceCurrentInstall "1"
!macroend
