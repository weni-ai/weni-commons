from enum import Enum


class Action(str, Enum):
    ADD = "ADD"
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"

    @classmethod
    def to_choices(cls):
        return [(action.value, action.value) for action in cls]
