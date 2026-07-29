from enum import Enum


class Entity(str, Enum):
    USER = "USER"
    FLOW = "FLOW"
    CHANNEL = "CHANNEL"
    TRIGGER = "TRIGGER"
    CAMPAIGN = "CAMPAIGN"
    QUEUE = "QUEUE"
    SECTOR = "SECTOR"
    HOLIDAY = "HOLIDAY"
    WORKING_HOURS = "WORKING_HOURS"

    @classmethod
    def to_choices(cls):
        return [(entity.value, entity.value) for entity in cls]
