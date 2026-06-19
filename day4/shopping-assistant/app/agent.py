# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os
import google.auth

try:
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
except Exception:
    project_id = "mock-project-id"
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
if "GEMINI_API_KEY" not in os.environ:
    os.environ["GEMINI_API_KEY"] = "MOCK_GEMINI_API_KEY"


# In-memory store for discount codes and registered users
VALID_DISCOUNT_CODES = {"WELCOME50", "SUMMER20"}
REDEEMED_DISCOUNT_CODES = set()
REGISTERED_USERS = {"user123", "user456", "student_1", "kaggle_student"}


def redeem_discount_code(user_id: str, discount_code: str) -> str:
    """Redeems a single-use discount code for a registered user.

    Args:
        user_id: The registered user ID requesting redemption.
        discount_code: The discount code to redeem (e.g., WELCOME50, SUMMER20).

    Returns:
        A string message indicating whether the redemption was successful or why it failed.
    """
    if user_id not in REGISTERED_USERS:
        return f"Error: User ID '{user_id}' is not a registered user."

    code_upper = discount_code.strip().upper()
    if code_upper not in VALID_DISCOUNT_CODES:
        return f"Error: Discount code '{discount_code}' is invalid."

    if code_upper in REDEEMED_DISCOUNT_CODES:
        return f"Error: Discount code '{discount_code}' has already been redeemed."

    REDEEMED_DISCOUNT_CODES.add(code_upper)
    return f"Success: Discount code '{code_upper}' successfully redeemed for user '{user_id}'!"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are an AI shopping assistant for a retail store. Assist customers with inquiries, recommend items, and help them redeem discount codes using the redeem_discount_code tool (which requires a registered user ID).",
    tools=[redeem_discount_code],
)

app = App(
    root_agent=root_agent,
    name="app",
)
