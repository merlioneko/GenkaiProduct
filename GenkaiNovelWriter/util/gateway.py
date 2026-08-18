from openai import OpenAI

def connect(model):
    url = "http://localhost:1234/v1"
    api_key = "lm-studio"
    client = OpenAI(base_url=url, api_key=api_key)
    try:
        client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": "接続テスト。OKとだけ返してください。"}]
        )
    except Exception as e:
        raise ConnectionError(f"Failed to connect to the API: {e}")
    return client

def generate_text(client, system, user) -> str:
    if client is None:
        raise ValueError("Client is not connected. Please call connect() first.")
    response = client.chat.completions.create(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ]
    )
    result = response.choices[0].message.content
    return result