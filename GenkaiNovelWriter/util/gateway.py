import json
from abc import ABC, abstractmethod

from openai import BadRequestError
from openai import OpenAI
from util.tools import Tavily
from pydantic import BaseModel

MAX_SEARCH_RESULTS = 5
MAX_RESULT_CONTENT_LENGTH = 1000
MAX_SEARCH_CONTEXT_LENGTH = 6000
from util.file import read_json

def create_message(history: list = [], system:str = "", user:str = "") -> list:
    message =[
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]
    if history:
        message = history + message
    return message

class OpenAiApiGateWay(ABC):
    def __init__(self, model):
        self.model = model
        self.client = None

    @abstractmethod
    def connect(self):
        pass

    def chat_response(self, message: list, response_format: str | None = None):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        return self.client.chat.completions.create(
            model=self.model,
            messages=message
        )

    def chat_formated(self, message: list, base_model: type[BaseModel]) -> BaseModel:
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")

        response = self.client.chat.completions.parse(
            model=self.model,
            messages=message,
            response_format=base_model
        )
        if response.choices[0].message.parsed:
            return response.choices[0].message.parsed
        else:
            raise ValueError("Failed to parse the response.")

    def chat(self, messages):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        try:
            return self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
        except BadRequestError as error:
            if "exceed_context_size_error" in str(error):
                raise RuntimeError(
                    "検索結果を含む入力がモデルのコンテキスト上限を超えました。"
                    "検索結果の件数または本文の長さを減らすか、LM Studio のコンテキスト長を増やしてください。"
                ) from error
            raise

    def chat_with_tool(self, system, user, tool):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            tools=tool,
            tool_choice="required"
        )
        return response.choices[0].message


class LmStudioGateway(OpenAiApiGateWay):
    def connect(self, url="http://localhost:1234/v1", api_key="lm-studio"):
        self.client = OpenAI(base_url=url, api_key=api_key)

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

class OpenRouterGateWay(OpenAiApiGateWay):
    def connect(self):
        openrouter = read_json(".env/gateway.json")["openrouter"]
        url = openrouter["url"]
        api_key = openrouter["api_key"]
        self.client = OpenAI(base_url=url, api_key=api_key)

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

def generate_formated(gateway, system: str, user: str, base_model: type[BaseModel], history:list = []) -> BaseModel:
    if gateway.client is None:
        raise ValueError("Client is not connected. Please call connect() first.")
    response = gateway.chat_formated(
        create_message(history=history, system=system, user=user),
        base_model=base_model
        )
    return response

def _compact_search_result(result) -> str:
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)[:MAX_SEARCH_CONTEXT_LENGTH]

    compact_results = []
    for item in result.get("results", [])[:MAX_SEARCH_RESULTS]:
        if not isinstance(item, dict):
            continue
        compact_results.append({
            "title": item.get("title", ""),
            "content": str(item.get("content", ""))[:MAX_RESULT_CONTENT_LENGTH],
            "url": item.get("url", ""),
        })

    return json.dumps(
        {"results": compact_results},
        ensure_ascii=False,
    )[:MAX_SEARCH_CONTEXT_LENGTH]


def generate_with_search(gateway: OpenAiApiGateWay, system, user, search_tool: Tavily):
    result = search_tool.execute(user)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {
            "role": "user",
            "content": "検索結果:\n" + _compact_search_result(result),
        },
    ]
    response = gateway.chat(messages)
    return response.choices[0].message.content