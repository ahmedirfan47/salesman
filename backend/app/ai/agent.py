"""The tool-calling agent loop.

Given the conversation so far, the model either replies to the customer or
calls a tool. When it calls a tool, we run the real implementation, feed the
result back, and let it continue -- until it produces a final reply.

The model NEVER states a price or stock level itself: it must call
get_price_and_stock. That rule lives in the system prompt AND is enforced by
the fact that only tools can read the database.
"""
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import tools
from app.ai.llm import chat

_MAX_STEPS = 6

SYSTEM_PROMPT = """You are "Salesman", a professional AI sales assistant for {business}.

Your job: help customers on WhatsApp check products and prices, and place orders.

Hard rules:
- NEVER invent or guess a price, total, or stock quantity. To quote any price or
  availability, you MUST call get_price_and_stock first and use exactly what it returns.
- If the customer names a product but you don't know its SKU, call search_products.
- Before placing an order, confirm the items and quantities with the customer.
- Only call place_order after the customer confirms.
- If place_order returns needs_human_review = true, tell the customer politely that
  you're checking availability with the team and will confirm shortly. Do not promise
  the order is confirmed.
- Detect the language the customer is writing in (English or Arabic) and always reply
  in that same language.
- Be concise, friendly, and professional -- like a real salesperson, not a robot.
"""


def _msg_to_dict(m) -> dict:
    """Convert an assistant message object (with tool_calls) to a plain dict
    suitable for sending back in the next request."""
    d: dict = {"role": "assistant", "content": m.content or ""}
    if getattr(m, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in m.tool_calls
        ]
    return d


async def run_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    business_name: str,
    history: list[dict],
    user_message: str,
) -> dict:
    """Run one customer turn. Returns {reply, steps} where steps lists any tools used."""
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(business=business_name)},
        *history,
        {"role": "user", "content": user_message},
    ]

    steps: list[dict] = []

    for _ in range(_MAX_STEPS):
        assistant = await chat(messages, tools=tools.TOOL_SCHEMAS)
        messages.append(_msg_to_dict(assistant))

        tool_calls = getattr(assistant, "tool_calls", None)
        if not tool_calls:
            return {"reply": assistant.content or "", "steps": steps}

        # execute each requested tool and feed results back
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await tools.dispatch(db, tenant_id, tc.function.name, args)
            steps.append({"tool": tc.function.name, "args": args, "result": result})
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {
        "reply": "I'm having trouble completing that right now. Let me get a human to help.",
        "steps": steps,
    }