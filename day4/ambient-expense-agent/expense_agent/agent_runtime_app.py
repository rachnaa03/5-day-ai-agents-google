# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Event-driven FastAPI runtime application for the ambient expense approval agent."""

import json
import logging
import os
from typing import Any
from unittest.mock import MagicMock

import google.auth
import google.auth.credentials
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field
from vertexai.agent_engines.templates.adk import AdkApp

from expense_agent.agent import app as adk_app
from expense_agent.app_utils.typing import Feedback

# Load environment variables from .env file at runtime
load_dotenv()

# Set up local authentication mock if Vertex AI is disabled and credentials are not present
use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "True").lower() == "true"
if not use_vertex:
    try:
        google.auth.default()
    except Exception:
        mock_credentials = MagicMock(spec=google.auth.credentials.Credentials)
        google.auth.default = lambda *args, **kwargs: (
            mock_credentials,
            os.environ.get("GOOGLE_CLOUD_PROJECT", "dummy-project-id"),
        )

# Configure telemetry according to the checklist: Set otel_to_cloud=False
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"

# Configure logging according to the checklist: Use standard Python logging for console logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("expense_agent")


class RobustLogger:
    def __init__(self, gcloud_logger: Any = None) -> None:
        self.local_logger = logging.getLogger("expense_agent")

    def log_struct(self, info: dict[str, Any], severity: str = "INFO") -> None:
        log_level = getattr(logging, severity, logging.INFO)
        self.local_logger.log(log_level, f"Log Struct: {info}")


class AgentEngineApp(AdkApp):
    """Subclass of AdkApp kept for backward compatibility and testing."""

    def set_up(self) -> None:
        super().set_up()
        self.logger = RobustLogger()

    def register_feedback(self, feedback: dict[str, Any]) -> None:
        feedback_obj = Feedback.model_validate(feedback)
        self.logger.log_struct(feedback_obj.model_dump(), severity="INFO")

    def register_operations(self) -> dict[str, list[str]]:
        operations = super().register_operations()
        operations[""] = [*operations.get("", []), "register_feedback"]
        return operations

    def clone(self) -> "AgentEngineApp":
        return self


agent_runtime = AgentEngineApp(app=adk_app)

# Initialize Session Service for the FastAPI application
session_service = InMemorySessionService()

# FastAPI Web Service
app = FastAPI(
    title="Ambient Expense Approval Agent Event-Driven Service",
    description="Accepts Pub/Sub trigger events and runs the approval workflow.",
    version="0.1.0",
)


# Pub/Sub request validation models
class PubSubMessage(BaseModel):
    data: str | None = Field(default=None, description="Base64-encoded message data.")
    attributes: dict[str, str] | None = Field(
        default=None, description="Message attributes."
    )
    messageId: str | None = Field(default=None, description="Pub/Sub message ID.")
    publishTime: str | None = Field(default=None, description="Publish timestamp.")


class PubSubTriggerRequest(BaseModel):
    message: PubSubMessage
    subscription: str | None = Field(
        default=None,
        description="Full subscription name (e.g. projects/p/subscriptions/s).",
    )


class ResumePayload(BaseModel):
    decision: str = Field(description="Decision: 'Approve' or 'Reject'")
    user_id: str = Field(
        description="Short subscription name matching the session owner"
    )


@app.post("/")
@app.post("/trigger/pubsub")
@app.post("/apps/expense_agent/trigger/pubsub")
async def trigger_pubsub(req: PubSubTriggerRequest) -> dict[str, Any]:
    """Pub/Sub push subscription trigger endpoint.

    Accepts Pub/Sub messages, extracts fully-qualified subscription path,
    normalizes it down to a short name, and feeds the payload into the workflow.
    """
    subscription = req.subscription or "pubsub-caller"

    # Gotcha: Normalize the fully-qualified subscription name down to the short name
    subscription_short = subscription.split("/")[-1]
    user_id = subscription_short

    # Create unique session ID using messageId (or fallback to generated id)
    message_id = req.message.messageId or "default-msg-id"
    session_id = f"session-{message_id}"

    logger.info(
        "Received Pub/Sub message. Subscription: %s -> Normalized User: %s",
        subscription,
        user_id,
    )

    # Ensure session exists
    session = await session_service.get_session(
        app_name="expense_agent", user_id=user_id, session_id=session_id
    )
    if not session:
        session = await session_service.create_session(
            app_name="expense_agent", user_id=user_id, session_id=session_id
        )

    # Pass the pubsub message wrapper serialized as JSON to the workflow
    payload_dict = {
        "data": req.message.data,
        "attributes": req.message.attributes or {},
    }
    payload_str = json.dumps(payload_dict)

    message_content = types.Content(
        role="user", parts=[types.Part.from_text(text=payload_str)]
    )

    runner = Runner(
        agent=adk_app.root_agent,
        session_service=session_service,
        app_name="expense_agent",
    )

    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=message_content,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    # Inspect events to check if we yielded a RequestInput (workflow is paused)
    is_paused = False
    for event in events:
        if (
            event.content
            and event.content.parts
            and any(
                p.function_call and p.function_call.name == "adk_request_input"
                for p in event.content.parts
            )
        ):
            is_paused = True
            break

    if is_paused:
        logger.info(
            "Workflow execution paused for human approval. Session: %s",
            session_id,
        )
        return {
            "status": "paused",
            "session_id": session_id,
            "user_id": user_id,
            "message": (
                "Expense requires human approval. Submit decision to"
                " /sessions/{session_id}/resume"
            ),
        }

    # If completed, extract final output
    output_data = {}
    for event in events:
        if event.output:
            output_data = event.output

    logger.info("Workflow execution completed. Result: %s", output_data)
    return {
        "status": "completed",
        "session_id": session_id,
        "user_id": user_id,
        "result": output_data,
    }


@app.post("/sessions/{session_id}/resume")
async def resume_session(session_id: str, payload: ResumePayload) -> dict[str, Any]:
    """Resume a workflow session waiting for human approval decision."""
    user_id = payload.user_id

    # Retrieve active session
    session = await session_service.get_session(
        app_name="expense_agent", user_id=user_id, session_id=session_id
    )
    if not session:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found for user {user_id}.",
        )

    logger.info(
        "Resuming session %s for user %s with decision: %s",
        session_id,
        user_id,
        payload.decision,
    )

    # Construct the function response resume message expected by ADK
    resume_message = types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id="approval_decision",
                    name="adk_request_input",
                    response={"result": payload.decision},
                )
            )
        ],
    )

    runner = Runner(
        agent=adk_app.root_agent,
        session_service=session_service,
        app_name="expense_agent",
    )

    events = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=resume_message,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    output_data = {}
    for event in events:
        if event.output:
            output_data = event.output

    logger.info("Workflow execution completed after resume. Result: %s", output_data)
    return {
        "status": "completed",
        "session_id": session_id,
        "user_id": user_id,
        "result": output_data,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("expense_agent.agent_runtime_app:app", host="127.0.0.1", port=8080)
