"""Answering and SSE streaming endpoints."""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi import Request as FastAPIRequest
from fastapi.responses import StreamingResponse

from ..answering import answer_question
from ..auth import Principal, principal
from ..models import ChatRequest
from ..utils import json_dumps

router = APIRouter()


@router.post("/api/chat")
def chat(payload: ChatRequest, p: Principal = Depends(principal)) -> dict[str, Any]:
    return answer_question(p, payload)



@router.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest, request: FastAPIRequest, p: Principal = Depends(principal)) -> StreamingResponse:

    async def events() -> AsyncIterator[str]:
        try:
            response = await asyncio.to_thread(answer_question, p, payload)
            yield f"event: citations\ndata: {json_dumps({'citations': response['citations'], 'trace_id': response['trace_id']})}\n\n"
            for token in re.findall(r"\S+\s*", response["answer"]):
                if await request.is_disconnected():
                    return
                yield f"event: token\ndata: {json_dumps({'text': token})}\n\n"
                await asyncio.sleep(0)
            yield f"event: done\ndata: {json_dumps(response)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json_dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
