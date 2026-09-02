from tavily import TavilyClient
from .file import read_env

class Tavily:
    def __init__(self, client: TavilyClient=TavilyClient(api_key=read_env("tavily.md"))):
        self.client = client
        self.tool = [
            {
                "type": "function",
                "function": {
                    "name": "tavily_search",
                    "description": "最新のニュース、事実関係、一般的なウェブ検索を行うための検索エンジン",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "検索キーワード（例: '最新のAIニュース 2026年'）",
                            },
                        },
                        "required": ["query"],
                    },
                },
            }
    ]

    def execute(self, query):
        response = self.client.search(
            query=query,
            search_depth="advanced"
        )
        return response

def test():
    client = TavilyClient(api_key=read_env("tavily.md"))
    tavily_tool = Tavily(client)
    result = tavily_tool.execute("最新のAIニュース 2026年")
    print(result)

if __name__ == "__main__":
    test()