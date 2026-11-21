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


class AgentSettingsOut(BaseModel):
    review_min_confidence: float
    review_quantity_multiple: int
    learn_aliases: bool
    review_all_ai_orders: bool
