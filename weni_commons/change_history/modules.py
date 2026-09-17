from enum import Enum


class Module(str, Enum):
    FLOWS = "FLOWS"
    LIVE_DESK = "LIVE_DESK"
    NEXUS = "NEXUS"

    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    INSTRUCTIONS = "INSTRUCTIONS"
    MY_AGENTS = "MY_AGENTS"

    @classmethod
    def to_choices(cls):
        return [(module.value, module.value) for module in cls]
