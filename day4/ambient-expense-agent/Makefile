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

.PHONY: install playground test lint

# Install project dependencies
install:
	uv sync

# Run the local ADK Web Playground
playground:
	uvx google-agents-cli playground

# Run the local event-driven web service
run:
	uv run python -m expense_agent.agent_runtime_app

# Run the unit and integration tests
test:
	uv run pytest tests/unit tests/integration

# Run code style, quality, and type checks
lint:
	uvx google-agents-cli lint

