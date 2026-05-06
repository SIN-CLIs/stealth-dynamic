# anti-learn.md — Anti-Patterns (stealth-dynamic)

> **Zweck**: Fehlermuster die NIE WIEDER auftreten dürfen.

---

## ❌ Absolute Verbote

1. **NIE webauto-nodriver** verwenden — ABSOLUT BANNED in der Stealth Suite
2. **NIE skylight-cli click --element-index** — BANNED; aber snapshot-compact + batch = PRIMARY (RE-ACTIVATED)
3. **NIE CDP für Navigation/Klicks** — nur JS execute/evaluate erlaubt
4. **NIE pyautogui/pynput** — Mausbewegung ist verboten
5. **NIE `pkill -f "heypiggy-bot"`** — killt ALLE Chrome-Instanzen

## ❌ Doc-System

- **NIE** Dateien ohne W-Fragen-Kommentare erstellen
- **NIE** fehlende Pflichtdateien ignorieren — Doc-Health-Check läuft

> Updated 2026-05-06 per learn.md — see SIN-CLIs/stealth-runner
