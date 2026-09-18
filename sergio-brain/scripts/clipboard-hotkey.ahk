; AutoHotkey v2 - CTRL+ALT+S captura el portapapeles al Inbox de SERGIO BRAIN (opcional; el plugin de Obsidian
; ya ofrece el mismo atajo dentro de Obsidian). Requiere el motor corriendo (sergio-brain serve).
^!s::
{
    clip := A_Clipboard
    if (clip = "") {
        TrayTip("Sergio Brain", "Portapapeles vacío", 1)
        return
    }
    body := '{"text": ' . JsonString(clip) . ', "capture_type": "clipboard", "source": {"source_type": "clipboard", "capture_method": "hotkey"}}'
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("POST", "http://127.0.0.1:8765/capture", false)
        req.SetRequestHeader("Content-Type", "application/json")
        req.Send(body)
        TrayTip("Sergio Brain", SubStr(req.ResponseText, 1, 200), 1)
    } catch as e {
        TrayTip("Sergio Brain", "Motor apagado: " . e.Message, 1)
    }
}

JsonString(s) {
    s := StrReplace(s, "\", "\\")
    s := StrReplace(s, '"', '\"')
    s := StrReplace(s, "`r", "\r")
    s := StrReplace(s, "`n", "\n")
    s := StrReplace(s, "`t", "\t")
    return '"' . s . '"'
}
