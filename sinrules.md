# sinrules.md — stealth-dynamic: Regeln & Verbote

> **← [stealth-runner/sinrules.md](https://github.com/OpenSIN-AI/stealth-runner/blob/main/sinrules.md) ist das zentrale Regelwerk.**
> Alle Golden Rules sind DORT definiert. Diese Datei ist der Repo-spezifische Mirror.
> **Gültig ab**: 2026-05-05

---

## §1 — Stealth Suite Compliance

Dieses Repo (stealth-dynamic) ist Teil der **SIN-CLIs Stealth Suite** und MUSS:
1. Alle Regeln aus [stealth-runner/sinrules.md](https://github.com/OpenSIN-AI/stealth-runner/blob/main/sinrules.md) befolgen
2. BANNED Tools vermeiden: webauto-nodriver (absolut), CDP Navigation (banned); skylight-cli RE-ACTIVATED (snapshot-compact + batch = PRIMARY)
3. NEMO Architektur für Browser-Interaktion respektieren (CUA-Only ist LEGACY)
4. Pipeline: perceive → plan → guard → execute → critique

## §2 — Repo-spezifische Verbote

- NIE ohne Pipeline guard.execute() ausführen
- NIE Koordinaten-basiertes Klicken (pyautogui/pynput)
- NIE CDP für Navigation/Klicks
- NIE `pkill -f "heypiggy-bot"` oder `killall Google Chrome`

## §3 — Pflicht-Dokumentation

Alle 14 Pflichtdateien MÜSSEN existieren und aktuell sein.
Check mit: `python3 /Users/jeremy/dev/stealth-runner/scripts/check_doc_health.py --repo stealth-dynamic`

**Letztes Update**: 2026-05-05
> Updated 2026-05-06 per learn.md — see SIN-CLIs/stealth-runner
