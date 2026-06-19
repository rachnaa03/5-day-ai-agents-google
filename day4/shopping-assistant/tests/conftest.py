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
from unittest.mock import AsyncMock, MagicMock

import google.auth
import google.cloud.logging
import google.genai
from google.genai import types

# Mock google.auth.default to prevent credentials search during test collection
mock_creds = MagicMock()
google.auth.default = lambda *args, **kwargs: (mock_creds, "mock-project-id")

# Set standard testing environment variables
os.environ["GOOGLE_CLOUD_PROJECT"] = "mock-project-id"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
os.environ["GEMINI_API_KEY"] = "MOCK_GEMINI_API_KEY"


# Mock google.cloud.logging.Client to avoid GCP credential calls
class MockLoggingClient:
    def __init__(self, *args, **kwargs):
        pass

    def logger(self, name):
        mock_logger = MagicMock()
        mock_logger.log_struct = MagicMock()
        return mock_logger


google.cloud.logging.Client = MockLoggingClient

# Save original Client __init__
original_init = google.genai.Client.__init__


def mocked_init(self, *args, **kwargs):
    # Ensure api_key is passed to avoid key missing validation in client constructor
    if "api_key" not in kwargs and not os.environ.get("GEMINI_API_KEY"):
        kwargs["api_key"] = "MOCK_GEMINI_API_KEY"

    original_init(self, *args, **kwargs)

    # Mock async generate_content
    self.aio.models.generate_content = AsyncMock(
        return_value=types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(
                                text="This is a mock response from the shopping assistant."
                            )
                        ],
                    )
                )
            ]
        )
    )

    # Mock async generate_content_stream
    async def mock_stream(*args, **kwargs):
        async def generator():
            yield types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part.from_text(
                                    text="This is a mock response chunk from the shopping assistant."
                                )
                            ],
                        )
                    )
                ]
            )

        return generator()

    self.aio.models.generate_content_stream = mock_stream


google.genai.Client.__init__ = mocked_init
