"""DynamicSurveyEngine — AX-first, CDP-JS Fallback für versteckte Formulare (Toluna etc.)."""
import re, time, logging, json, urllib.request, websocket
from .classifier import SurveyClassifier
from .resolver import QuestionResolver
from .flow_state import FlowStateMachine, SurveyState
logger = logging.getLogger(__name__)

DEFAULT_PERSONA = {
    "gender": "male", "age": 42, "city": "Berlin", "plz": "10785",
    "street": "Kurfürstenstraße 124", "bundesland": "Berlin",
    "income": "mittel", "education": "Hochschule",
    "job": "Angestellter", "household": "2 Personen",
}

class DynamicSurveyEngine:
    def __init__(self, executor, window_manager, model_router, persona=None):
        self.executor = executor
        self.wm = window_manager
        self.router = model_router
        self.persona = persona or DEFAULT_PERSONA
        self.classifier = SurveyClassifier()
        self.resolver = QuestionResolver(persona=self.persona)
        self.flow = FlowStateMachine()
        self._cdp_ws = None

    # ── Public API ──────────────────────────────────────────────────────────

    def handle_page(self) -> dict:
        """AX-first, CDP-JS Fallback für versteckte Formulare."""
        pid = self.executor.cache.get_pid()
        wid = self.executor.cache.get_active_window()
        tree = self.executor._cua("get_state", {"pid": pid, "window_id": wid})
        ax_md = tree.get("data", {}).get("tree_markdown", "")
        page_type = self.classifier.classify(ax_md)
        logger.info("Page type: %s (q=%d)", page_type, self.flow.current_question)

        # ── Consent ─────────────────────────────────────────────────────
        if page_type == "consent":
            self.flow.transition(SurveyState.CONSENT)
            btn = re.search(r'\[(\d+)\].*AXButton.*[Zz]ustimmen', ax_md)
            if btn:
                return self.executor.execute({"tool":"cua-touch","action":"click",
                    "params":{"element_index":int(btn.group(1)),"pid":pid,"window_id":wid,"verify":True}})
            return {"error": "consent button not found"}

        # ── Completed ───────────────────────────────────────────────────
        if page_type == "completed":
            self.flow.transition(SurveyState.COMPLETED)
            return {"status": "completed", "questions": self.flow.current_question}

        # ── Question page ───────────────────────────────────────────────
        if page_type != "unknown":
            self.flow.transition(SurveyState.QUESTION)

            # Versuche zuerst AX-basiert
            action = self.resolver.resolve(page_type, ax_md, self.router)
            if action.get("action") in ("click", "set_value"):
                # Prüfe ob Elemente im AX-Tree sichtbar sind
                if self._has_ax_elements(ax_md, action):
                    params = {**action, "pid": pid, "window_id": wid, "verify": True}
                    result = self.executor.execute({"tool":"cua-touch","action":action["action"],"params":params})
                    self._wait_and_click_continue_ax(pid, wid)
                    return result

            # Fallback: CDP-JS für versteckte Formulare (Toluna-Pattern)
            logger.info("AX elements not found – using CDP-JS fallback")
            cdp_result = self._answer_via_cdp()
            return cdp_result

        # ── Unknown ─────────────────────────────────────────────────────
        self.flow.transition(SurveyState.ERROR)
        result = self.executor.execute({"tool":"context","action":"get_all","params":{}})
        return {"error": "unknown_page_type", "ax_md_length": len(ax_md), "targets": result}

    # ── CDP-JS Fallback für Toluna/versteckte Formulare ─────────────────────

    def _answer_via_cdp(self) -> dict:
        try:
            ws = self._get_cdp_ws()
            persona_json = json.dumps(self.persona)

            # ── SPA Detection: Framework erkennen + DOM-Stabilität warten ──
            from .spa_detector import detect_framework, find_elements_script, wait_stable_dom_script
            framework_info = detect_framework(ws)
            fw = framework_info.get("framework", "unknown")
            spa_frameworks = ("React", "Angular", "Vue", "Next.js", "Nuxt")

            # Wenn SPA erkannt: MutationObserver warten + Framework-Selektoren nutzen
            if fw in spa_frameworks:
                logger.info("SPA detected: %s — using MutationObserver + framework selectors", fw)
                # 1. Warte auf DOM-Stabilität
                ws.send(json.dumps({"id":100,"method":"Runtime.evaluate","params":{"expression":wait_stable_dom_script(3000)}}))
                ws.recv()
                # 2. Finde Elemente via Framework-Selektoren
                ws.send(json.dumps({"id":101,"method":"Runtime.evaluate","params":{"expression":find_elements_script(fw)}}))
                elements = json.loads(ws.recv()).get("result",{}).get("result",{}).get("value",[])
                visible = [e for e in elements if e.get("visible")]
                if visible:
                    # Baue Answer-Script aus den gefundenen Elementen
                    answer = self._build_spa_answer(visible, fw)
                    return {"success": True, "action": answer, "framework": fw, "elements_found": len(visible)}
                # Fallback: keine sichtbaren Elemente via Framework
                logger.info("SPA %s: no visible elements via framework selectors", fw)

            # ── Universal Answer Script (Standard / Fallback) ──
            script = self._CDP_ANSWER_TEMPLATE.replace("__PERSONA__", persona_json)
            ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":script}}))
            resp = json.loads(ws.recv())
            result = resp.get("result",{}).get("result",{}).get("value","")

            # Fast skip if incompatible platform (<1s detection)
            if result == 'NO_ELEMENTS':
                ws.close()
                return {"success": False, "action": "incompatible", "body_preview": "", "progress": "", "completed": False}

            ws.send(json.dumps({"id":2,"method":"Runtime.evaluate","params":{"expression":
                "document.body?.innerText?.substring(0,300) || ''"
            }}))
            body = json.loads(ws.recv()).get("result",{}).get("result",{}).get("value","")

            ws.send(json.dumps({"id":3,"method":"Runtime.evaluate","params":{"expression":
                "document.querySelector('[name=\"__prevPageProgress\"]')?.value || ''"
            }}))
            progress = json.loads(ws.recv()).get("result",{}).get("result",{}).get("value","")

            completed = any(k in body.lower() for k in ['danke','abgeschlossen','completed','vielen dank'])
            if completed:
                self.flow.transition(SurveyState.COMPLETED)

            return {
                "success": not result.startswith("ERROR"),
                "action": result,
                "body_preview": body[:100].strip(),
                "progress": progress,
                "completed": completed,
            }
        except Exception as e:
            logger.error("CDP answer failed: %s", e)
            return {"success": False, "error": str(e)}

    def _build_spa_answer(self, elements: list, framework: str) -> str:
        """Baut Answer aus SPA-Elementen: klicke erste Option in jeder Gruppe."""
        ws = None
        try:
            ws = self._get_cdp_ws()
            parts = []
            for el in elements:
                if el.get("checked"): continue
                tag, typ, idx, name = el.get("tag",""), el.get("type",""), el.get("x",""), el.get("name","")
                if tag in ("INPUT",) and typ in ("radio", "checkbox"):
                    selector = f'input[name="{name}"]'
                    parts.append(f'document.querySelector(\'{selector}\')?.click()')
                    break  # nur erstes pro Name
            if parts:
                script = "(()=>{" + ";".join(parts) + ";return 'spa_ok'})()"
                ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":script}}))
                result = json.loads(ws.recv()).get("result",{}).get("result",{}).get("value","?")
                return f"spa:{result}"
            return "spa:no_elements"
        except Exception as e:
            return f"spa:error:{e}"
        finally:
            if ws: ws.close()

    _CDP_ANSWER_TEMPLATE = r"""
    (() => {
        const P = __PERSONA__;
        const BODY = (document.body?.innerText || '').toLowerCase();
        let acts = [];

        // 0. Fast platform detection: check if ANY form elements exist (<1s)
        const hasElements = document.querySelectorAll('input[type="radio"],input[type="checkbox"],input[type="text"],input[type="number"],button').length;
        if (hasElements === 0) return 'NO_ELEMENTS';

        function getContext(el) {
            let ctx = (el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').toLowerCase();
            let p = el;
            for (let i = 0; i < 5; i++) {
                p = p.parentElement;
                if (!p) break;
                ctx += ' ' + (p.textContent || '').substring(0, 80).toLowerCase();
            }
            return ctx + ' ' + BODY;
        }

        // Hilfsfunktion: Label-Text eines Radio/Checkbox-Elements finden
        function getLabel(el) {
            if (el.labels && el.labels.length > 0)
                return (el.labels[0].textContent || '').trim().toLowerCase();
            let next = el.nextElementSibling;
            while (next && next.tagName === 'SPAN') {
                const t = (next.textContent || '').trim().toLowerCase();
                if (t) return t;
                next = next.nextElementSibling;
            }
            if (el.previousElementSibling)
                return (el.previousElementSibling.textContent || '').trim().toLowerCase();
            // Tiefere Suche: parent text
            const parentText = (el.parentElement?.textContent || '').trim().toLowerCase();
            return parentText.substring(0, 40);
        }

        // 1. LEERE Textfelder persona-basiert füllen (mit Kontext-Analyse)
        document.querySelectorAll('input[type="text"], input[type="number"], input[type="tel"]').forEach(el => {
            if (!el.value || el.value.trim() === '' || el.value === 'Test') {
                const ctx = getContext(el);
                if (/plz|postleitzahl|zip/.test(ctx)) {
                    el.value = P.plz || '10115';
                } else if (/alter|age|jahre|jahr/.test(ctx)) {
                    el.value = '' + (P.age || 42);
                } else if (/stadt|ort|wohnort|city/.test(ctx)) {
                    el.value = P.city || 'Berlin';
                } else if (/bundesland/.test(ctx)) {
                    el.value = P.bundesland || 'Berlin';
                } else if (/vorname|first.?name/.test(ctx)) {
                    el.value = 'Manfred';
                } else if (/nachname|last.?name/.test(ctx)) {
                    el.value = 'M\u00fcller';
                } else if (/strasse|adresse|street/.test(ctx)) {
                    el.value = 'Hauptstra\u00dfe 1';
                } else if (/haushalt|personen/.test(ctx)) {
                    el.value = P.household || '2';
                } else {
                    el.value = '42';
                }
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                acts.push('txt:' + (el.id || el.name));
            }
        });

        // 2. Geschlecht persona-basiert
        document.querySelectorAll('input[type="radio"]').forEach(el => {
            const ctx = getContext(el);
            if (/geschlecht|gender|sex/.test(ctx)) {
                const lbl = getLabel(el);
                if (P.gender === 'male' && /männlich|mann|male|herr/.test(lbl)) { el.click(); acts.push('gdr:m'); }
                if (P.gender === 'female' && /weiblich|frau|female/.test(lbl)) { el.click(); acts.push('gdr:f'); }
            }
        });

        // 2. Radio-Gruppen: NUR unbeantwortete klicken, persona-basiert
        document.querySelectorAll('input[type="radio"]').forEach(el => {
            const name = el.getAttribute('name') || el.id;
            const parent = el.parentElement?.textContent?.toLowerCase() || '';
            const label = (el.labels?.[0]?.textContent || el.nextSibling?.textContent || '').toLowerCase();

            // Geschlecht: persona-basiert
            if (/geschlecht|gender|sex/.test(parent)) {
                if (P.gender === 'male' && /männlich|mann|male|herr/.test(label)) { el.click(); acts.push('gender:m'); return; }
                if (P.gender === 'female' && /weiblich|frau|female/.test(label)) { el.click(); acts.push('gender:f'); return; }
            }
        });

        // 3. UNBEANTWORTETE Radio-Gruppen
        const rGrp = {};
        document.querySelectorAll('input[type="radio"]').forEach(el => {
            const n = el.getAttribute('name') || el.id;
            if (!rGrp[n]) rGrp[n] = {els: [], checked: false};
            rGrp[n].els.push(el);
            if (el.checked) rGrp[n].checked = true;
        });
        Object.values(rGrp).forEach(g => {
            if (!g.checked && g.els.length > 0) {
                // Erster nicht-"keine Angabe" option
                for (const el of g.els) {
                    const lbl = getLabel(el);
                    if (!/nicht beantworten|keine angabe|wei\u00df nicht|keine/i.test(lbl) && !el.checked) {
                        el.click(); acts.push('rad:' + (el.name || el.id)); return;
                    }
                }
                // Fallback: erste option
                for (const el of g.els) {
                    if (!el.checked) { el.click(); acts.push('rad-fb'); return; }
                }
            }
        });

        // 4. UNBEANTWORTETE Checkbox-Gruppen (mind. eine pro Gruppe)
        const cGrp = {};
        document.querySelectorAll('input[type="checkbox"]').forEach(el => {
            const n = el.getAttribute('name') || el.id;
            if (!cGrp[n]) cGrp[n] = {els: [], checked: false};
            cGrp[n].els.push(el);
            if (el.checked) cGrp[n].checked = true;
        });
        Object.values(cGrp).forEach(g => {
            if (!g.checked) {
                for (const el of g.els) {
                    if (!el.checked) { el.click(); acts.push('chk'); return; }
                }
            }
        });

        // 4.5 BUTTON-basierte Surveys (modern, kein input[type=radio])
        if (acts.length === 0) {
            document.querySelectorAll('button').forEach(btn => {
                const t = btn.textContent.trim();
                if (t && !t.includes('Weiter') && !t.includes('\u2192') && acts.length === 0) {
                    btn.click(); acts.push('btn:' + t.substring(0,20));
                    // Klicke Weiter nach kurzer Pause
                    setTimeout(() => {
                        document.querySelectorAll('button').forEach(b => {
                            if (/weiter|\u2192/.test(b.textContent)) b.click();
                        });
                    }, 300);
                }
            });
        }

        // 5. Weiter
        const fwd = document.getElementById('forwardbutton')
            || document.querySelector('input[type="submit"]:not([style*="-9000"])')
            || document.querySelector('button[type="submit"]');
        if (fwd) {
            fwd.click();
            return 'OK ' + acts.length + ': ' + acts.slice(0,5).join(', ');
        }
        return 'ERR: no forward button';
    })()
    """

    # ── AX-Weiter-Klick ─────────────────────────────────────────────────────

    def _wait_and_click_continue_ax(self, pid, wid, fast=False):
        """Wartet auf 'Weiter'-Button im AX-Tree (0.3s Polling in fast mode)."""
        delay = 0.3 if fast else 1.0
        for _ in range(30 if fast else 15):
            tree = self.executor._cua("get_state", {"pid": pid, "window_id": wid})
            for line in tree.get("data",{}).get("tree_markdown","").split("\n"):
                if "weiter" in line.lower() and "AXButton" in line:
                    m = re.search(r'\[(\d+)\]', line)
                    if m:
                        self.executor.execute({"tool":"cua-touch","action":"click",
                            "params":{"element_index":int(m.group(1)),"pid":pid,"window_id":wid,"verify":True}})
                        return True
            time.sleep(delay)
        return False

    # ── Hilfsfunktionen ─────────────────────────────────────────────────────

    def _has_ax_elements(self, ax_md, action):
        """Prüft ob die gesuchten Elemente überhaupt im AX-Tree sind."""
        if action.get("label") and action["label"] in ax_md:
            return True
        return "AXRadioButton" in ax_md or "AXTextField" in ax_md

    def _get_cdp_ws(self):
        """Liefert CDP WebSocket zum aktuellen Survey-Tab (nicht heypiggy)."""
        port = self.executor.cache.get_cdp_port()
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5)
        targets = json.loads(r.read())
        # Priority 1: Known survey platforms
        for t in targets:
            if t.get("type") == "page":
                url = t.get("url","")
                if any(k in url for k in ["survey","toluna","samplicio","cint","civey","nfield","question","umfrage"]):
                    return websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
        # Priority 2: Any non-heypiggy page
        for t in targets:
            if t.get("type") == "page" and "heypiggy" not in t.get("url",""):
                return websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
        # Fallback
        for t in targets:
            if t.get("type") == "page":
                return websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
        raise RuntimeError("No page target found")
