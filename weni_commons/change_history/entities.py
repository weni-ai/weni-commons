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

    # Nexus
    CONTENT_BASE = "CONTENT_BASE"
    CONTENT_BASE_AGENT = "CONTENT_BASE_AGENT"
    CONTENT_BASE_FILE = "CONTENT_BASE_FILE"
    CONTENT_BASE_INSTRUCTION = "CONTENT_BASE_INSTRUCTION"
    CONTENT_BASE_LINK = "CONTENT_BASE_LINK"
    CONTENT_BASE_TEXT = "CONTENT_BASE_TEXT"
    INTELLIGENCE = "INTELLIGENCE"
    LLM = "LLM"
    PROJECT = "PROJECT"

    @classmethod
    def to_choices(cls):
        return [(entity.value, entity.value) for entity in cls]
