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