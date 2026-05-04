"""DynamicSurveyEngine — AX-first, CDP-JS Fallback für versteckte Formulare (Toluna etc.)."""
import re, time, logging, json, urllib.request, websocket
from .classifier import SurveyClassifier
from .resolver import QuestionResolver
from .flow_state import FlowStateMachine, SurveyState
logger = logging.getLogger(__name__)

DEFAULT_PERSONA = {
    "gender": "male", "age": 42, "city": "Berlin", "plz": "10115",
    "bundesland": "Berlin", "income": "mittel", "education": "Hochschule",
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
            script = self._CDP_ANSWER_TEMPLATE.replace("__PERSONA__", persona_json)
            ws.send(json.dumps({"id":1,"method":"Runtime.evaluate","params":{"expression":script}}))
            resp = json.loads(ws.recv())
            result = resp.get("result",{}).get("result",{}).get("value","")

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

    _CDP_ANSWER_TEMPLATE = """
    (() => {
        const P = __PERSONA__;
        let acts = [];

        // 1. LEERE Textfelder persona-basiert füllen
        document.querySelectorAll('input[type="text"], input[type="number"], input[type="tel"]').forEach(el => {
            if (!el.value || el.value.trim() === '') {
                const ctx = (el.parentElement?.textContent || el.getAttribute('placeholder') || el.ariaLabel || '').toLowerCase();
                if (/plz|postleitzahl|zip/.test(ctx))
                    el.value = P.plz || '10115';
                else if (/alter|age|jahre|jahr/.test(ctx))
                    el.value = '' + (P.age || 42);
                else if (/stadt|ort|wohnort|city/.test(ctx))
                    el.value = P.city || 'Berlin';
                else if (/bundesland|land/.test(ctx))
                    el.value = P.bundesland || 'Berlin';
                else if (/vorname|first.*name/.test(ctx))
                    el.value = 'Manfred';
                else if (/nachname|last.*name/.test(ctx))
                    el.value = 'Müller';
                else if (/strasse|adresse|street/.test(ctx))
                    el.value = 'Hauptstraße 1';
                else if (/haushalt|personen/.test(ctx))
                    el.value = P.household || '2';
                else if (/name/.test(ctx))
                    el.value = 'Manfred';
                else
                    el.value = '42';
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                acts.push('txt:' + (el.id || el.name));
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

        // 3. UNBEANTWORTETE Radio-Gruppen (eine pro name)
        const rGrp = {};
        document.querySelectorAll('input[type="radio"]').forEach(el => {
            const n = el.getAttribute('name') || el.id;
            if (!rGrp[n]) rGrp[n] = {els: [], checked: false};
            rGrp[n].els.push(el);
            if (el.checked) rGrp[n].checked = true;
        });
        Object.values(rGrp).forEach(g => {
            if (!g.checked) {
                // Wähle NICHT "keine Angabe" oder "nicht beantworten" wenn möglich
                for (const el of g.els) {
                    const lbl = (el.labels?.[0]?.textContent || '').toLowerCase();
                    if (!/nicht beantworten|keine angabe|weiß nicht|keine/.test(lbl) && !el.checked) {
                        el.click(); acts.push('rad:' + (el.name || el.id)); return;
                    }
                }
                // Fallback: erste Option
                for (const el of g.els) {
                    if (!el.checked) { el.click(); acts.push('rad-fb:' + (el.name || el.id)); return; }
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

    def _wait_and_click_continue_ax(self, pid, wid):
        """Wartet auf 'Weiter'-Button im AX-Tree und klickt ihn."""
        for _ in range(15):
            tree = self.executor._cua("get_state", {"pid": pid, "window_id": wid})
            for line in tree.get("data",{}).get("tree_markdown","").split("\n"):
                if "weiter" in line.lower() and "AXButton" in line:
                    m = re.search(r'\[(\d+)\]', line)
                    if m:
                        self.executor.execute({"tool":"cua-touch","action":"click",
                            "params":{"element_index":int(m.group(1)),"pid":pid,"window_id":wid,"verify":True}})
                        return True
            time.sleep(1)
        return False

    # ── Hilfsfunktionen ─────────────────────────────────────────────────────

    def _has_ax_elements(self, ax_md, action):
        """Prüft ob die gesuchten Elemente überhaupt im AX-Tree sind."""
        if action.get("label") and action["label"] in ax_md:
            return True
        return "AXRadioButton" in ax_md or "AXTextField" in ax_md

    def _get_cdp_ws(self):
        """Liefert CDP WebSocket zum aktuellen Survey-Tab."""
        port = self.executor.cache.get_cdp_port()
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=5)
        targets = json.loads(r.read())
        for t in targets:
            if t.get("type") == "page" and "survey" in t.get("url","") or "toluna" in t.get("url",""):
                return websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
        # Fallback: erster page target
        for t in targets:
            if t.get("type") == "page":
                return websocket.create_connection(t["webSocketDebuggerUrl"], suppress_origin=True, timeout=10)
        raise RuntimeError("No page target found")
