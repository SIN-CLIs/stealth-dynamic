from enum import Enum

class SurveyState(Enum):
    INIT = "init"
    LOGIN = "login"
    CONSENT = "consent"
    QUESTION = "question"
    WAITING = "waiting"
    ERROR = "error"
    COMPLETED = "completed"

class FlowStateMachine:
    def __init__(self):
        self.state = SurveyState.INIT
        self.history = []
        self.current_question = 0

    def transition(self, new_state: SurveyState, context: dict = None):
        self.history.append({"from": self.state.value, "to": new_state.value, "context": context or {}})
        self.state = new_state
        if new_state == SurveyState.QUESTION:
            self.current_question += 1
        if len(self.history) > 100:
            self.history = self.history[-50:]

    def recovery_path(self):
        for step in reversed(self.history):
            if step["to"] not in ("error", "waiting"):
                return step
        return None

    def get_state(self) -> dict:
        return {"state": self.state.value, "question": self.current_question,
                "history_count": len(self.history), "last_step": self.history[-1] if self.history else None}
