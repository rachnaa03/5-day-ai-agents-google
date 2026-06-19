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

import os
import pytest
from unittest.mock import AsyncMock
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
import google.genai

from app.agent import root_agent, REDEEMED_DISCOUNT_CODES


@pytest.fixture(autouse=True)
def clean_redeemed_codes():
    """Fixture to clear the redeemed discount codes before each test."""
    REDEEMED_DISCOUNT_CODES.clear()
    yield
    REDEEMED_DISCOUNT_CODES.clear()


def setup_mock_client(monkeypatch, mock_responses):
    """Helper to mock the Client initialization and return custom responses."""
    original_init = google.genai.Client.__init__

    mock_generate = AsyncMock()
    mock_generate.side_effect = mock_responses

    def custom_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.aio.models.generate_content = mock_generate

    monkeypatch.setattr(google.genai.Client, "__init__", custom_init)

    # Reset any existing clients on the root_agent's model using dict deletion
    if "_client" in root_agent.model.__dict__:
        del root_agent.model.__dict__["_client"]
    if "api_client" in root_agent.model.__dict__:
        del root_agent.model.__dict__["api_client"]


@pytest.mark.asyncio
async def test_agent_redeem_discount_success(monkeypatch) -> None:
    """Verifies that the agent successfully executes the discount tool for valid inputs."""
    mock_responses = [
        # First call: Model decides to call the tool
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_function_call(
                                name="redeem_discount_code",
                                args={"user_id": "user123", "discount_code": "WELCOME50"}
                            )
                        ]
                    )
                )
            ]
        ),
        # Second call: Model acknowledges the success output from the tool
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(text="Success: Discount code 'WELCOME50' successfully redeemed for user 'user123'!")
                        ]
                    )
                )
            ]
        )
    ]

    setup_mock_client(monkeypatch, mock_responses)

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="user123", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Please redeem WELCOME50 for user123")]
    )

    events = list(runner.run(
        new_message=message,
        user_id="user123",
        session_id=session.id
    ))

    assert len(events) > 0
    assert "WELCOME50" in REDEEMED_DISCOUNT_CODES


@pytest.mark.asyncio
async def test_agent_redeem_discount_unregistered_user(monkeypatch) -> None:
    """Verifies that the agent fails to redeem when the user is unregistered."""
    mock_responses = [
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_function_call(
                                name="redeem_discount_code",
                                args={"user_id": "unknown_user", "discount_code": "WELCOME50"}
                            )
                        ]
                    )
                )
            ]
        ),
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(text="Error: User ID 'unknown_user' is not a registered user.")
                        ]
                    )
                )
            ]
        )
    ]

    setup_mock_client(monkeypatch, mock_responses)

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="unknown_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Please redeem WELCOME50 for unknown_user")]
    )

    events = list(runner.run(
        new_message=message,
        user_id="unknown_user",
        session_id=session.id
    ))

    assert len(events) > 0
    assert "WELCOME50" not in REDEEMED_DISCOUNT_CODES


@pytest.mark.asyncio
async def test_agent_redeem_discount_invalid_code(monkeypatch) -> None:
    """Verifies that the agent fails to redeem when the code is invalid."""
    mock_responses = [
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_function_call(
                                name="redeem_discount_code",
                                args={"user_id": "user123", "discount_code": "INVALID50"}
                            )
                        ]
                    )
                )
            ]
        ),
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(text="Error: Discount code 'INVALID50' is invalid.")
                        ]
                    )
                )
            ]
        )
    ]

    setup_mock_client(monkeypatch, mock_responses)

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="user123", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Please redeem INVALID50 for user123")]
    )

    events = list(runner.run(
        new_message=message,
        user_id="user123",
        session_id=session.id
    ))

    assert len(events) > 0
    assert "INVALID50" not in REDEEMED_DISCOUNT_CODES


@pytest.mark.asyncio
async def test_agent_redeem_discount_already_redeemed(monkeypatch) -> None:
    """Verifies that the agent blocks double-redemption of a single-use code."""
    # Pre-redeem the code
    REDEEMED_DISCOUNT_CODES.add("WELCOME50")

    mock_responses = [
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_function_call(
                                name="redeem_discount_code",
                                args={"user_id": "user456", "discount_code": "WELCOME50"}
                            )
                        ]
                    )
                )
            ]
        ),
        types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(text="Error: Discount code 'WELCOME50' has already been redeemed.")
                        ]
                    )
                )
            ]
        )
    ]

    setup_mock_client(monkeypatch, mock_responses)

    session_service = InMemorySessionService()
    session = session_service.create_session_sync(user_id="user456", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user",
        parts=[types.Part.from_text(text="Please redeem WELCOME50 for user456")]
    )

    events = list(runner.run(
        new_message=message,
        user_id="user456",
        session_id=session.id
    ))

    assert len(events) > 0
    assert "WELCOME50" in REDEEMED_DISCOUNT_CODES
