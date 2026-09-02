from openai import Omit, OpenAI
from util.file import read_json

def create_message(history: list = [], system:str = "", user:str = "") -> list:
    message =[
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]
    if history:
        message = history + message
    return message

class LmStudioGateway:
    def __init__(self, model):
        self.model = model
        self.client = None

    def connect(self):
        url = "http://localhost:1234/v1"
        api_key = "lm-studio"
        self.client = OpenAI(base_url=url, api_key=api_key)

    def chat_response(self, message: list, response_format: dict = {}):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")

        # TODO: response_formatの実装

        return self.client.chat.completions.create(
            model=self.model,
            messages=message
        )

def connect_lm_studio(model):
    client = LmStudioGateway(model)
    try:
        client.connect()
        result = client.chat_response(
            create_message(system="This session is Test mode. Don't Thinking.", user="Only say Ok")
            ).choices[0].message.content
        if not result:
            raise ConnectionError(f"Failed to connect to the API: Unexpected response from the server. Expected 'Ok', got '{result}'")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the API: {e}")
    return client

class OpenRouterGateWay:
    def __init__(self, model):
        self.model = model
        self.client = None
    def connect(self):
        openrouter = read_json(".env/key.json")["openrouter"]
        url = openrouter["url"]
        api_key = openrouter["api_key"]
        self.client = OpenAI(base_url=url, api_key=api_key)
    def chat_response(self, message: list, response_format: str | None = None):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        return self.client.chat.completions.create(
            model=self.model,
            messages=message,
            response_format=response_format
        )

def connect_openrouter(model):
    client = OpenRouterGateWay(model)
    try:
        client.connect()
        result = client.chat_response(
            create_message(system="This session is Test mode. Don't Thinking.", user="Only say Ok")
            ).choices[0].message.content
        if not result:
            raise ConnectionError(f"Failed to connect to the API: Unexpected response from the server. Expected 'Ok', got '{result}'")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the API: {e}")
    return client

def generate_text(gateway, system: str, user: str, history:list = []) -> str:
    if gateway.client is None:
        raise ValueError("Client is not connected. Please call connect() first.")
    response = gateway.chat_response(
        create_message(history=history, system=system, user=user)
        )
    result = response.choices[0].message.content
    return result
