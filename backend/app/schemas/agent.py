from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatStep(BaseModel):
    tool: str
    args: dict
    result: dict


class ChatResponse(BaseModel):
    reply: str
    steps: list[ChatStep]

class AgentSettingsIn(BaseModel):
    review_min_confidence: float | None = Field(default=None, ge=0, le=1)
    review_quantity_multiple: int | None = Field(default=None, ge=0, le=100)
    learn_aliases: bool | None = None
    review_all_ai_orders: bool | None = None
    reorder_enabled: bool | None = None
    reorder_factor: float | None = Field(default=None, ge=1, le=5)
    reorder_min_orders: int | None = Field(default=None, ge=2, le=50)
    reorder_template: str | None = Field(default=None, max_length=120)   # "" clears it
    message_retention_days: int | None = Field(default=None, ge=0, le=3650)  # 0 keeps messages


class AgentSettingsOut(BaseModel):
    review_min_confidence: float
    review_quantity_multiple: int
    learn_aliases: bool
    review_all_ai_orders: bool
    reorder_enabled: bool = False
    reorder_factor: float = 1.25
    reorder_min_orders: int = 3
    reorder_template: str | None = None
    message_retention_days: int | None = None
