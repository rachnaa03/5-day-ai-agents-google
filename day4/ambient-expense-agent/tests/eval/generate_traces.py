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

"""Helper script to run local evaluation cases and generate formatted trace outputs."""

import asyncio
import json
import os
from pathlib import Path

# Configure local mocks and disable cloud tracing/telemetry
os.environ["GOOGLE_CLOUD_PROJECT"] = "dummy-project-id"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
# os.environ["GEMINI_API_KEY"] = "dummy-api-key"
os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from expense_agent.agent import root_agent


def format_adk_content(content) -> dict:
    """Format ADK/Gemini Content object into standard dictionary structure."""
    if not content:
        return {}
    parts = []
    for p in content.parts or []:
        part_dict = {}
        if p.text is not None:
            part_dict["text"] = p.text
        if p.function_call is not None:
            part_dict["function_call"] = {
                "name": p.function_call.name,
                "id": p.function_call.id,
                "args": p.function_call.args,
            }
        if p.function_response is not None:
            part_dict["function_response"] = {
                "name": p.function_response.name,
                "id": p.function_response.id,
                "response": p.function_response.response,
            }
        parts.append(part_dict)
    return {"role": content.role or "model", "parts": parts}


async def run_case(case: dict) -> dict:
    """Execute a single evaluation case and capture its multi-turn trace."""
    case_id = case["eval_case_id"]
    prompt_text = case["prompt"]["parts"][0]["text"]

    session_service = InMemorySessionService()
    runner = Runner(
        agent=root_agent,
        session_service=session_service,
        app_name="expense_agent",
    )

    user_id = "eval-user"
    session_id = f"session-{case_id}"

    # Setup the execution session
    await session_service.create_session(
        app_name="expense_agent", user_id=user_id, session_id=session_id
    )

    initial_message = types.Content(
        role="user", parts=[types.Part.from_text(text=prompt_text)]
    )

    turns = []
    events_turn_0 = []

    # Record initial user message
    events_turn_0.append(
        {
            "author": "user",
            "content": {"role": "user", "parts": [{"text": prompt_text}]},
        }
    )

    # Run the first turn of the agent workflow
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=initial_message,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        if event.content:
            events_turn_0.append(
                {
                    "author": "agent",
                    "content": format_adk_content(event.content),
                }
            )

    turns.append({"turn_index": 0, "turn_id": "turn_0", "events": events_turn_0})

    # Check if execution paused waiting for human approval
    is_paused = False
    for event_dict in events_turn_0:
        content = event_dict.get("content") or {}
        parts = content.get("parts") or []
        for p in parts:
            if p.get("function_call", {}).get("name") == "adk_request_input":
                is_paused = True
                break

    final_text = ""

    if is_paused:
        # Determine human decision automatically (Reject for rejection_case, Approve for others)
        decision = "Reject" if case_id == "rejection_case" else "Approve"
        print(
            f"[{case_id}] Workflow paused. Resuming automatically with"
            f" decision: {decision}"
        )

        resume_message = types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id="approval_decision",
                        name="adk_request_input",
                        response={"result": decision},
                    )
                )
            ],
        )

        events_turn_1 = []
        events_turn_1.append(
            {
                "author": "user",
                "content": {
                    "role": "user",
                    "parts": [
                        {
                            "function_response": {
                                "name": "adk_request_input",
                                "id": "approval_decision",
                                "response": {"result": decision},
                            }
                        }
                    ],
                },
            }
        )

        # Resume the session and execute the remaining workflow nodes
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=resume_message,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            if event.content:
                events_turn_1.append(
                    {
                        "author": "agent",
                        "content": format_adk_content(event.content),
                    }
                )

        turns.append({"turn_index": 1, "turn_id": "turn_1", "events": events_turn_1})

        # Capture final agent outcome summary text
        for event_dict in reversed(events_turn_1):
            content = event_dict.get("content") or {}
            parts = content.get("parts") or []
            texts = [
                str(p["text"]) for p in parts if "text" in p and p["text"] is not None
            ]
            if texts:
                final_text = "".join(texts)
                break
    else:
        # Capture final agent outcome text (auto-approved instantly)
        for event_dict in reversed(events_turn_0):
            content = event_dict.get("content") or {}
            parts = content.get("parts") or []
            texts = [
                str(p["text"]) for p in parts if "text" in p and p["text"] is not None
            ]
            if texts:
                final_text = "".join(texts)
                break

    # Build EvalCase matching Gemini Enterprise Agent Platform format
    eval_case = {
        "eval_case_id": case_id,
        "prompt": {"role": "user", "parts": [{"text": prompt_text}]},
        "agent_data": {"turns": turns},
    }
    if final_text:
        eval_case["responses"] = [
            {"response": {"role": "model", "parts": [{"text": final_text}]}}
        ]

    return eval_case


async def main():
    dataset_path = Path("tests/eval/datasets/basic-dataset.json")
    output_path = Path("artifacts/generated_traces.json")

    print(f"Loading dataset from {dataset_path}...")
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    cases = dataset.get("eval_cases") or []
    generated_cases = []

    for case in cases:
        print(f"Running case: {case['eval_case_id']}...")
        eval_case = await run_case(case)
        generated_cases.append(eval_case)

    output_data = {"eval_cases": generated_cases}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    print(f"Traces written to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
