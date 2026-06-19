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

"""Pytest configuration and global mocks for Google Cloud services."""

import os
from unittest.mock import MagicMock

import google.auth
import google.auth.credentials
import google.cloud.logging

# Set dummy environment variables to prevent Vertex AI initialization errors during testing
os.environ["GOOGLE_CLOUD_PROJECT"] = "dummy-project-id"
os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
os.environ["GEMINI_API_KEY"] = "dummy-api-key"

# Mock google.auth.default to return dummy credentials and project
mock_credentials = MagicMock(spec=google.auth.credentials.Credentials)
google.auth.default = lambda *args, **kwargs: (mock_credentials, "dummy-project-id")

# Mock google.cloud.logging.Client to prevent external API calls
mock_logging_client = MagicMock()
mock_logger = MagicMock()
mock_logging_client.logger.return_value = mock_logger
google.cloud.logging.Client = lambda *args, **kwargs: mock_logging_client
