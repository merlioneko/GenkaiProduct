from util.tools import Tavily

def test():
    tavily_tool = Tavily()
    result = tavily_tool.execute("最新のAIニュース 2026年")
    print(result)

if __name__ == "__main__":
    test()