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
        

    def send_message(self, message:str, system_prompt: str) -> str:
        self._validate_str(message, "message")

        response = self.conn.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ])
        
        if response.choices[0].message.content is not None:
            return response.choices[0].message.content
        
        raise RuntimeError("AI response is empty")

    def close(self):
        self.conn.close()

    
        
    
    