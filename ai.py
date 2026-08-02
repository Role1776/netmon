"""Small OpenAI-compatible client wrapper used by optional Remote AI.

Netmon keeps the provider boundary deliberately narrow: Groq exposes an
OpenAI-compatible chat-completions endpoint, so the existing OpenAI SDK can be
reused without introducing a second provider-specific dependency.
"""

from __future__ import annotations

from openai import OpenAI


class Client:
    """Context-managed chat client with explicit connection timeout."""

    def __init__(self, conn: OpenAI, model: str):
        self.conn = conn
        self.model = model

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.conn.close()

    @staticmethod
    def _validate_str(value: str, field_name: str) -> None:
        if not value.strip():
            raise ValueError(f"{field_name} cannot be empty")

    @classmethod
    def init(
        cls,
        api_key: str,
        model: str,
        base_url: str,
        request_timeout: int = 30,
    ) -> "Client":
        """Create a client without logging or otherwise exposing the API key."""

        cls._validate_str(api_key, "api_key")
        cls._validate_str(model, "model")
        cls._validate_str(base_url, "base_url")
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")

        return cls(
            OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=request_timeout,
            ),
            model,
        )

    def send_message(self, message: str, system_prompt: str) -> str:
        """Send one stateless chat-completions request and return plain text."""

        self._validate_str(message, "message")
        self._validate_str(system_prompt, "system_prompt")

        response = self.conn.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
        )

        content = response.choices[0].message.content
        if content is not None and content.strip():
            return content

        raise RuntimeError("AI response is empty")

    def close(self) -> None:
        self.conn.close()
