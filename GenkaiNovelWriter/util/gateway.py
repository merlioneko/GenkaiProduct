from openai import OpenAI

class LmStudioGateway:
    def __init__(self, model):
        self.model = model
        self.client = None

    def connect(self):
        url = "http://localhost:1234/v1"
        api_key = "lm-studio"
        self.client = OpenAI(base_url=url, api_key=api_key)

    def chat_response(self, system, user):
        if self.client is None:
            raise ValueError("Client is not connected. Please call connect() first.")
        return self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ]
        )

def connect_lm_studio(model):
    client = LmStudioGateway(model)
    try:
        client.connect()
        result = client.chat_response("", "Only say Ok").choices[0].message.content
        if not result:
            raise ConnectionError(f"Failed to connect to the API: Unexpected response from the server. Expected 'Ok', got '{result}'")
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the API: {e}")
    return client

def generate_text(gateway, system, user) -> str:
    if gateway.client is None:
        raise ValueError("Client is not connected. Please call connect() first.")
    response = gateway.chat_response(system, user)
    result = response.choices[0].message.content
    return result