from enum import Enum


class Module(str, Enum):
    FLOWS = "FLOWS"
    LIVE_DESK = "LIVE_DESK"
    NEXUS = "NEXUS"

    @classmethod
    def to_choices(cls):
        return [(module.value, module.value) for module in cls]
