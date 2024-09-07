class StrategySettings:
    def __init__(self, settings_json):
        self.settings = settings_json

    def get(self, key, default=None):
        return self.settings.get(key, default)