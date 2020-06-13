import json

class Request:
    def __init__(self):
        self.module: str = ""
        self.action: str = ""

    def __repr__(self):
        return json.dumps(self.__dict__)
