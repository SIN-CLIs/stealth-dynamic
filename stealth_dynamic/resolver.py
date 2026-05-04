import re

class QuestionResolver:
    def __init__(self, persona: dict = None):
        self.persona = persona or {"gender": "male", "age": 42}

    def resolve(self, page_type: str, ax_markdown: str, router) -> dict:
        strategies = {
            "radio_question": self._answer_radio,
            "checkbox_question": self._answer_checkbox,
            "text_question": self._answer_text,
            "math_question": self._answer_math,
            "image_question": self._answer_image,
            "audio_question": self._answer_audio,
            "video_question": self._answer_video,
            "matrix_question": self._answer_matrix,
            "captcha": self._solve_captcha,
        }
        handler = strategies.get(page_type, self._unknown)
        return handler(ax_markdown, router)

    def _answer_radio(self, ax, router):
        radios = re.findall(r'AXRadioButton\s+"([^"]+)"', ax)
        indices = re.findall(r'\[(\d+)\]\s+AXRadioButton', ax)
        for i, label in enumerate(radios):
            if self._matches_persona(label):
                return {"action": "click", "index": int(indices[i]), "label": label}
        for i, label in enumerate(radios):
            if not any(n in label.lower() for n in ["nein", "nie", "schlecht"]):
                return {"action": "click", "index": int(indices[i]), "label": label}
        if radios:
            return {"action": "click", "index": int(indices[0]), "label": radios[0]}
        return {"action": "click_first_radio"}

    def _answer_checkbox(self, ax, router):
        return {"action": "click_first_checkbox"}

    def _answer_text(self, ax, router):
        m = re.search(r'AXTextField\s+"([^"]*)"', ax)
        val = "Standard"
        ll = ax.lower()
        p = self.persona
        if "plz" in ll or "postleitzahl" in ll:
            val = str(p.get("plz", "10115"))
        elif "alter" in ll or "alter" in ll:
            val = str(p.get("age", 42))
        elif "stadt" in ll or "ort" in ll:
            val = str(p.get("city", "Berlin"))
        elif "name" in ll:
            val = "Manfred Müller"
        return {"action": "set_value", "value": val, "placeholder": m.group(1) if m else ""}

    def _answer_math(self, ax, router):
        return {"action": "solve_math", "model": router.route("solve_math")["name"]}

    def _answer_image(self, ax, router):
        return {"action": "screenshot_and_analyze", "model": "nemotron-omni"}

    def _answer_audio(self, ax, router):
        return {"action": "skip_or_transcribe"}

    def _answer_video(self, ax, router):
        return {"action": "play_and_observe"}

    def _answer_matrix(self, ax, router):
        return {"action": "answer_grid", "strategy": "first_positive_per_row"}

    def _solve_captcha(self, ax, router):
        return {"action": "solve_captcha"}

    def _unknown(self, ax, router):
        return {"action": "heavy_analyze", "model": router.route("analyze_new_provider")["name"]}

    def _matches_persona(self, label):
        p = self.persona
        if p.get("gender") == "male" and "männlich" in label.lower():
            return True
        if "ja" in label.lower():
            return True
        if p.get("age") and str(p.get("age")) in label:
            return True
        return False
