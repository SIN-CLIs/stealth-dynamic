# banned.md — Verbotene Methoden (stealth-dynamic)

> **← [stealth-runner/banned.md](https://github.com/OpenSIN-AI/stealth-runner/blob/main/banned.md) für vollständige Liste**

---

## ABSOLUT BANNED

| Tool/Methode | Grund | Ersatz |
|-------------|-------|--------|
| `webauto-nodriver` | MCP-Server, CDP-Missbrauch | NEMO / CDP WebSocket |
| `skylight-cli` | RE-ACTIVATED (click --element-index = still BANNED) | snapshot-compact + batch (PRIMARY) |
| CDP Navigation/Klicks | Chrome blockiert, unsicher | NEMO / CDP JS evaluate |
| `pyautogui` | Mausbewegung | cua-driver AXPress (LEGACY) |
| `pynput` | Mausbewegung | cua-driver AXPress (LEGACY) |
| `pkill -f "heypiggy-bot"` | Killt USER Chrome mit! | `SessionManager.close_all()` |

## BEDINGT ERLAUBT

| Tool | Bedingung |
|------|-----------|
| CDP JS evaluate | NUR für `Runtime.evaluate()` — keine Navigation |
| macos-ax-cli | NUR für System-Scan — nicht für Klicks |

**Letztes Update**: 2026-05-05
> Updated 2026-05-06 per learn.md — see SIN-CLIs/stealth-runner
