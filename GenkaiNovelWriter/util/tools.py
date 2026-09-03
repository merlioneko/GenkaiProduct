from tavily import TavilyClient
from util.env import ToolsConfig

class Tavily:
    def __init__(self, client: TavilyClient | None = None):
        if not client:
            client = TavilyClient(api_key=ToolsConfig().get_search_tool()["tavily"]["api_key"])
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