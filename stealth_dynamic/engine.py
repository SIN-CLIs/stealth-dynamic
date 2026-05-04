import re, time, logging
from .classifier import SurveyClassifier
from .resolver import QuestionResolver
from .flow_state import FlowStateMachine, SurveyState
logger = logging.getLogger(__name__)

class DynamicSurveyEngine:
    def __init__(self, executor, window_manager, model_router):
        self.executor = executor
        self.wm = window_manager
        self.router = model_router
        self.classifier = SurveyClassifier()
        self.resolver = QuestionResolver(persona={"gender": "male", "age": 42})
        self.flow = FlowStateMachine()

    def handle_page(self) -> dict:
        pid = self.executor.cache.get_pid()
        wid = self.executor.cache.get_active_window()
        tree = self.executor._cua("get_state", {"pid": pid, "window_id": wid})
        ax_md = tree.get("data", {}).get("tree_markdown", "")
        page_type = self.classifier.classify(ax_md)
        logger.info("Page type: %s (q=%d)", page_type, self.flow.current_question)

        if page_type == "consent":
            self.flow.transition(SurveyState.CONSENT)
            btn = re.search(r'\[(\d+)\].*AXButton.*[Zz]ustimmen', ax_md)
            if btn:
                return self.executor.execute({"tool":"cua-touch","action":"click",
                    "params":{"element_index":int(btn.group(1)),"pid":pid,"window_id":wid,"verify":True}})
            return {"error": "consent button not found"}

        if page_type == "completed":
            self.flow.transition(SurveyState.COMPLETED)
            return {"status": "completed", "questions": self.flow.current_question}

        if page_type != "unknown":
            self.flow.transition(SurveyState.QUESTION)
            action = self.resolver.resolve(page_type, ax_md, self.router)
            if action.get("action") in ("click", "set_value"):
                params = {**action, "pid": pid, "window_id": wid, "verify": True}
                result = self.executor.execute({"tool":"cua-touch","action":action["action"],"params":params})
            elif action.get("action") == "solve_math":
                result = {"action": "solve_math", "model": "deepseek-v4-pro"}
            else:
                result = {"action": action.get("action")}
            # Wait for and click "Weiter"
            self._wait_and_click_continue(pid, wid)
            return result

        self.flow.transition(SurveyState.ERROR)
        result = self.executor.execute({"tool":"context","action":"get_all","params":{}})
        return {"error": "unknown_page_type", "ax_md_length": len(ax_md), "targets": result}

    def _wait_and_click_continue(self, pid, wid):
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
