import json
import re
import warnings

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.core import make_agent
from agent.cli import summarize_tool_result, OUR_TOOLS

load_dotenv()
warnings.filterwarnings("ignore")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

agent = make_agent()

DOC_ID_RE = re.compile(
    r"(3P|BOM|DHF|DMR|DR|ECR|ESF|IFU|MEMO|PLN|QSR|RSK|TRA|VVAM|VVPR)"
    r"[-\s]*(?:(?:M02|MC2|SWV)[-\s]*)?\d+",
    re.IGNORECASE,
)
REV_RE = re.compile(r"Rev\s+([A-Z])", re.IGNORECASE)


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


def extract_sources(text: str) -> list[str]:
    seen: set[str] = set()
    sources: list[str] = []
    for match in DOC_ID_RE.finditer(text):
        doc_id = re.sub(r"\s+", "-", match.group(0).strip())
        end_pos = match.end()
        rev_match = REV_RE.search(text[end_pos:end_pos + 20])
        if rev_match:
            source = f"{doc_id} Rev {rev_match.group(1).upper()}"
        else:
            source = doc_id
        if source not in seen:
            seen.add(source)
            sources.append(source)
    return sources[:15]


def extract_content(msg) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return content.strip() if content else ""


@app.post("/chat")
def chat(req: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    result = agent.invoke({"messages": messages})
    ai_msg = result["messages"][-1]
    return {"reply": ai_msg.content}


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    def event_generator():
        for event in agent.stream({"messages": messages}):
            if "model" in event:
                msg = event["model"]["messages"][-1]
                content = extract_content(msg)
                tool_calls = getattr(msg, "tool_calls", None)

                if content and tool_calls:
                    yield f"data: {json.dumps({'type': 'reasoning', 'content': content})}\n\n"

                if tool_calls:
                    for tc in tool_calls:
                        if tc["name"] in OUR_TOOLS:
                            yield f"data: {json.dumps({'type': 'tool_call', 'name': tc['name'], 'args': tc['args']})}\n\n"

                if content and not tool_calls:
                    sources = extract_sources(content)
                    yield f"data: {json.dumps({'type': 'answer', 'content': content})}\n\n"
                    if sources:
                        yield f"data: {json.dumps({'type': 'sources', 'docs': sources})}\n\n"

            elif "tools" in event:
                tool_msg = event["tools"]["messages"][-1]
                tool_name = getattr(tool_msg, "name", "")
                if tool_name not in OUR_TOOLS:
                    continue
                tool_content = getattr(tool_msg, "content", "")
                if isinstance(tool_content, str):
                    summary = summarize_tool_result(tool_name, tool_content)
                    if summary:
                        yield f"data: {json.dumps({'type': 'tool_result', 'name': tool_name, 'summary': summary})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def main():
    import uvicorn

    uvicorn.run("agent.server:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
