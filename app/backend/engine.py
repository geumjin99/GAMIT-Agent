"""LLM engine: OpenAI-compatible interface, DeepSeek by default, base_url swappable (Claude/GPT/local).

A minimal OpenAI-compatible engine exposing only what the GAMIT-agent needs.
Interface: generate(system_prompt, user_message, stop) -> {"text", "tokens", "latency_ms"}
"""
import time
from typing import Optional, List, Dict, Any


class LLMEngine:
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com",
                 model: str = "deepseek-chat", temperature: float = 0.1,
                 max_tokens: int = 2048):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None
        self.total_calls = 0
        self.total_in_tokens = 0
        self.total_out_tokens = 0

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            kw = {"api_key": self.api_key}
            if self.base_url:
                kw["base_url"] = self.base_url
            self._client = OpenAI(**kw)
        return self._client

    def generate(self, system_prompt: str = "", user_message: str = "",
                 stop: Optional[List[str]] = None,
                 max_tokens: Optional[int] = None,
                 temperature: Optional[float] = None) -> Dict[str, Any]:
        if not self.api_key:
            return {"text": "Error: no API key configured.", "tokens": 0, "latency_ms": 0}
        if stop is None:
            stop = ["Observation:"]
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        t0 = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
                stop=stop,
            )
        except Exception as e:
            return {"text": f"Error during API call: {e}", "tokens": 0,
                    "latency_ms": (time.time() - t0) * 1000}

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        self.total_calls += 1
        if usage:
            self.total_in_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.total_out_tokens += getattr(usage, "completion_tokens", 0) or 0
        return {
            "text": text,
            "tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "latency_ms": (time.time() - t0) * 1000,
            "model": getattr(resp, "model", self.model),
        }
