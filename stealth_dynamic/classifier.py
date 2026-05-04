import re

class SurveyClassifier:
    def classify(self, ax_markdown: str) -> str:
        text = ax_markdown.lower()
        if "zustimmen" in text and "fortfahren" in text:
            return "consent"
        if any(k in text for k in ["danke", "abgeschlossen", "erfolgreich"]):
            return "completed"
        if "captcha" in text or "recaptcha" in text:
            return "captcha"
        if any(k in text for k in ["audio", "anhören", "abspielen", "lautsprecher"]):
            return "audio_question"
        if any(k in text for k in ["video", "ansehen", "abspielen"]):
            return "video_question"
        if "AXImage" in ax_markdown and "AXRadioButton" in ax_markdown:
            return "image_question"
        if re.search(r"\d+\s*[+\-×÷]\s*\d+", text):
            return "math_question"
        if ax_markdown.count("AXRadioButton") > 10:
            return "matrix_question"
        if "AXTextField" in ax_markdown:
            return "text_question"
        if "AXRadioButton" in ax_markdown:
            return "radio_question"
        if "AXCheckBox" in ax_markdown:
            return "checkbox_question"
        return "unknown"
