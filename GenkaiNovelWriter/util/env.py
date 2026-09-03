from util.file import read_json

from pathlib import Path

class ModelConfig:
    def __init__(self, config_file=".env/model.json"):
        self.config_file = config_file
        self.config_data = self.load_config()

    def load_config(self):
        return read_json(self.config_file)

    def get_model(self, role):
        if role not in self.config_data:
            raise ValueError(f"Role '{role}' not found in model configuration.")
        return self.config_data[role]

    def get_writer(self):
        return self.get_model("writer")

    def get_editor(self):
        return self.get_model("editor")

class ToolsConfig:
    def __init__(self, config_file=".env/tools.json"):
        self.config_file = config_file
        self.config_data = self.load_config()

    def load_config(self):
        return read_json(self.config_file)

    def get_tool(self, tool_name):
        if tool_name not in self.config_data:
            raise ValueError(f"Tool '{tool_name}' not found in tool configuration.")
        return self.config_data[tool_name]

    def get_search_tool(self):
        return self.get_tool("search")

def _test():
    model_config = ModelConfig()
    print("Writer Model:", model_config.get_writer())
    print("Editor Model:", model_config.get_editor())

    tools_config = ToolsConfig()
    print("Search Tool Config:", tools_config.get_search_tool())

if __name__ == "__main__":
    _test()