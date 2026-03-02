import requests


class OllamaClient:
    def __init__(self, model: str = "qwen2.5:3b"):
        self.model = model
        self.base_url = "http://localhost:11434"

    def generate(self, prompt: str) -> str:
        url = f"{self.base_url}/api/generate"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        return data.get("response", "").strip()