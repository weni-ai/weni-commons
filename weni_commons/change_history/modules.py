from enum import Enum


class Module(str, Enum):
    NEXUS = "NEXUS"
    LIVE_DESK = "LIVE_DESK"

    @classmethod
    def to_choices(cls):
        return [(module.value, module.value) for module in cls]
