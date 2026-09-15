import json
from abc import ABC, abstractmethod

from openai import BadRequestError
from openai import OpenAI
from util.settings import get_openrouter_base_url, get_required_secret
from pydantic import BaseModel
from typing import TypeVar

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)

def create_message(history: list = [], system:str = "", user:str = "") -> list:
    message =[
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]
    if history:
        message = history + message
    return message

class OpenAiApiGateWay(ABC):
    def __init__(self, model, base_url=None, api_key=None):
        self.model = model
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def chat_response(self, message: list):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        return self.client.chat.completions.create(
            model=self.model,
            messages=message
        )

    def chat_formatted(self, message: list, response_format: type[BaseModelT]) -> BaseModelT:
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")

        response = self.client.chat.completions.parse(
            model=self.model,
            messages=message,
            response_format=response_format
        )
        if response.choices[0].message.parsed:
            return response.choices[0].message.parsed
        else:
            raise ValueError("Failed to parse the response.")

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

def connect_lm_studio(model: str):
    client = OpenAiApiGateWay(model=model, base_url="http://localhost:1234/v1", api_key="lm-studio")
    try:
        result = client.chat_response(
            create_message(system="This session is Test mode. Don't Thinking.", user="Only say Ok")
            ).choices[0].message.content
        if not result:
            raise ConnectionError(f"Failed to connect to the API: Unexpected response from the server. Expected 'Ok', got '{result}'")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the API: {e}")
    return client

def connect_openrouter(model: str):
    client = OpenAiApiGateWay(model=str, base_url=get_openrouter_base_url(), api_key=get_required_secret("OPENROUTER_API_KEY"))
    try:
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
    print(f"System: {system}\nUser: {user}")
    response = gateway.chat_response(
        create_message(history=history, system=system, user=user)
        )
    result = response.choices[0].message.content
    return result


def generate_formatted(gateway, system: str, user: str, base_model: type[BaseModelT], history: list = []) -> BaseModelT:
    if gateway.client is None:
        raise ValueError("Client is not connected. Please call connect() first.")
    response = gateway.chat_formatted(
        create_message(history=history, system=system, user=user),
        base_model=base_model
        )
    return response
