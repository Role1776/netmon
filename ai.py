from openai import OpenAI

class Client:
    def __init__(self, conn: OpenAI, model: str): 
        self.conn: OpenAI = conn
        self.model: str = model

    def __enter__(self) -> "Client":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()

    @staticmethod
    def _validate_str(value: str, field_name: str):
        if value.strip() == "":
            raise ValueError(f"{field_name} cannot be empty")


    @classmethod
    def init(cls, api_key: str, model: str, base_url: str) -> "Client":
        Client._validate_str(api_key, "api_key")
        Client._validate_str(model, "model")
        Client._validate_str(base_url, "base_url")

        return cls(OpenAI(api_key=api_key, base_url=base_url), model)
        

    def send_message(
        self,
        message: str,
        system_prompt: str,
        temperature: float = 0.9,
        context_size: int | None = None,
    ) -> str:
        self._validate_str(message, "message")

        # Ollama's default context window (often 2048-4096 tokens depending
        # on the model) is easy to exceed once the system prompt plus a
        # day's worth of historical readings are combined — and unlike a
        # clear error, exceeding it just silently truncates the prompt
        # (typically from the start), which can quietly drop persona/format
        # instructions while leaving the raw data intact. Passing num_ctx
        # via extra_body raises this per-request for Ollama specifically.
        # This is a no-op / harmless on real OpenAI's API since it's only
        # added when context_size is explicitly set (e.g. for a local
        # Ollama backend), not unconditionally on every request.
        extra_body = {}
        if context_size is not None:
            extra_body["options"] = {"num_ctx": context_size}

        response = self.conn.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            extra_body=extra_body or None,
        )

        if response.choices[0].message.content is not None:
            return response.choices[0].message.content

        raise RuntimeError("AI response is empty")

    def close(self):
        self.conn.close()