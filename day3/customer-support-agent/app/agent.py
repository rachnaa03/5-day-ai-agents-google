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

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk import Workflow, Context
from google.adk.workflow import node, START, DEFAULT_ROUTE
from google.genai import types

import os

# Initialize Gemini models
classifier_model = Gemini(model="gemini-2.5-flash")
faq_model = Gemini(model="gemini-2.5-flash")

@node
async def classify_query(ctx: Context, node_input: str) -> str:
    query = node_input.lower()

    shipping_keywords = [
        "shipping",
        "rate",
        "tracking",
        "delivery",
        "return",
        "parcel",
        "package"
    ]

    if any(keyword in query for keyword in shipping_keywords):
        ctx.route = "shipping"
    else:
        ctx.route = "unrelated"

    return node_input

# FAQ Agent for shipping related queries
shipping_faq_agent = Agent(
    name="shipping_faq_agent",
    model=faq_model,
    instruction=(
        instruction="""
You are a shipping company customer support representative.

Answer ONLY using the following FAQ.

SHIPPING FAQ:

- Standard shipping: $5.99
- Express shipping: $12.99
- Orders above $50 qualify for free standard shipping.
- Standard delivery takes 3-5 business days.
- Express delivery takes 1-2 business days.
- Free returns within 30 days.
- Customers can track orders using the tracking page.

If the answer is not contained in the FAQ, politely say that the information is unavailable.
"""),
)

# Decline node for unrelated queries
@node
def decline_node(ctx: Context, node_input: str) -> str:
    """Politely declines to answer queries unrelated to shipping."""
    return (
        "I'm sorry, but I can only assist with queries related to shipping, "
        "such as shipping rates, tracking, delivery, and returns."
    )

# Build the customer support workflow
customer_support_workflow = Workflow(
    name="customer_support_workflow",
    edges=[
        (START, classify_query),
        (classify_query, {
            "shipping": shipping_faq_agent,
            "unrelated": decline_node
        })
    ]
)

app = App(
    root_agent=customer_support_workflow,
    name="app",
)

