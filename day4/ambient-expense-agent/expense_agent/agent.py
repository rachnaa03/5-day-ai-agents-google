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

"""Ambient Expense Approval Agent implemented as an ADK 2.0 Graph Workflow."""

import base64
import json
import os
import re

import google.auth
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import Workflow, node
from google.genai import types
from pydantic import BaseModel, Field

from expense_agent import config

load_dotenv()

# Check if using Vertex AI (default is True)
use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "True").lower() == "true"

if use_vertex:
    try:
        _, default_project_id = google.auth.default()
        if default_project_id:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", default_project_id)
    except Exception:
        pass
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"


# =====================================================================
# Security Helpers
# =====================================================================


def scrub_pii(text: str) -> str:
    """Scrubs SSNs and Credit Card numbers from the text, redacting variants."""
    # Scrub SSNs: 3 digits, followed by optional spaces/hyphens, 2 digits, optional spaces/hyphens, 4 digits
    ssn_pattern = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")
    text = ssn_pattern.sub("[REDACTED_SSN]", text)

    # Scrub 16-digit credit cards with optional spaces/hyphens between 4-digit groups
    cc_pattern = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")
    text = cc_pattern.sub("[REDACTED_CC]", text)

    # Scrub 15-digit credit cards (AMEX) with optional spaces/hyphens: 4 digits, 6 digits, 5 digits
    amex_pattern = re.compile(r"\b\d{4}[-\s]?\d{6}[-\s]?\d{5}\b")
    text = amex_pattern.sub("[REDACTED_CC]", text)

    return text


def detect_prompt_injection(text: str) -> bool:
    """Detects prompt injection markers trying to override threshold or auto-approve."""
    patterns = [
        "ignore previous",
        "ignore all previous",
        "ignore rules",
        "bypass rules",
        "force auto-approve",
        "system message",
        "system prompt",
        "you are now",
        "overwrite threshold",
        "skip review",
        "ignore threshold",
        "override threshold",
        "auto-approve this",
        "auto-approve instantly",
    ]
    text_lower = text.lower()
    return any(p in text_lower for p in patterns)


# =====================================================================
# Workflow Node Implementations
# =====================================================================


def parse_expense(node_input: types.Content) -> dict:
    """Parses incoming JSON events and extracts the expense details."""
    text = node_input.parts[0].text.strip()
    try:
        event = json.loads(text)
    except Exception as e:
        raise ValueError(f"Failed to parse input as JSON: {e}") from e

    # Details can sit directly at root or under a 'data' key (optionally base64 encoded)
    if "data" in event:
        data = event["data"]
        if isinstance(data, str):
            try:
                # Try decoding base64 Pub/Sub payload
                decoded = base64.b64decode(data).decode("utf-8")
                expense_data = json.loads(decoded)
            except Exception:
                try:
                    # Fallback to plain JSON string parsing
                    expense_data = json.loads(data)
                except Exception as e:
                    raise ValueError("Failed to parse 'data' string as JSON") from e
        elif isinstance(data, dict):
            expense_data = data
        else:
            raise TypeError("Unsupported 'data' field type in JSON event")
    else:
        expense_data = event

    # Extract required fields with type casting and sensible fallbacks
    return {
        "amount": float(expense_data.get("amount", 0.0)),
        "submitter": str(expense_data.get("submitter", "Unknown")),
        "category": str(expense_data.get("category", "Uncategorized")),
        "description": str(expense_data.get("description", "")),
        "date": str(expense_data.get("date", "")),
    }


def route_expense(node_input: dict) -> Event:
    """Decides whether the expense should be auto-approved or reviewed by an LLM."""
    amount = node_input["amount"]
    if amount < config.THRESHOLD:
        outcome = {
            "expense": node_input,
            "decision": "Approved (Auto-approved under $100)",
            "risk_assessment": "No review required (under threshold)",
        }
        # Save expense details in state for the final logging, and route to auto_approve
        return Event(
            output=outcome,
            actions=EventActions(
                route="auto_approve", state_delta={"current_expense": node_input}
            ),
        )
    else:
        # Route to risk review and save expense details in session state
        return Event(
            output=node_input,
            actions=EventActions(
                route="risk_review", state_delta={"current_expense": node_input}
            ),
        )


def security_checkpoint(ctx: Context, node_input: dict) -> Event:
    """Security checkpoint that scrubs PII and checks for prompt injection."""
    expense = dict(node_input)
    original_description = expense.get("description", "")

    # 1. Scrub PII (SSN and Credit Card numbers)
    scrubbed_description = scrub_pii(original_description)
    expense["description"] = scrubbed_description

    # 2. Defend against prompt injection
    if detect_prompt_injection(scrubbed_description):
        # Flag as security event, bypass LLM risk reviewer, route to human approval
        security_assessment = {
            "risk_factors": ["POTENTIAL PROMPT INJECTION DETECTED"],
            "alert_level": "CRITICAL",
            "explanation": (
                "Potential prompt injection attempt detected in the expense description. "
                "Bypassed LLM risk review for safety."
            ),
        }
        return Event(
            output=security_assessment,
            actions=EventActions(
                route="security_escalation",
                state_delta={"current_expense": expense},
            ),
        )
    else:
        # Proceed to LLM risk reviewer with scrubbed description
        return Event(
            output=expense,
            actions=EventActions(
                route="clean_expense",
                state_delta={"current_expense": expense},
            ),
        )


class RiskAssessment(BaseModel):
    """Pydantic model for structured LLM risk evaluation."""

    risk_factors: list[str] = Field(
        description="List of risk factors or policy violations identified in the expense report"
    )
    alert_level: str = Field(
        description="Calculated alert level, e.g. Low, Medium, High"
    )
    explanation: str = Field(
        description="A concise summary of why this alert level was assigned"
    )


# LLM node that analyzes the expense report details
risk_reviewer = LlmAgent(
    name="risk_reviewer",
    model=Gemini(
        model=config.MODEL,
    ),
    instruction=(
        "You are an expert corporate risk compliance auditor. "
        "Analyze the provided expense report details for risk factors. "
        "Look for suspicious amounts, mismatched categories and descriptions, "
        "off-hours dates, or unusual submission patterns. "
        "Provide a structured assessment containing risk_factors, alert_level, and a concise explanation."
    ),
    output_schema=RiskAssessment,
)


@node(rerun_on_resume=True)
async def human_approval(ctx: Context, node_input: dict):
    """Pauses the workflow for human validation of high-value/at-risk expenses."""
    expense = ctx.state["current_expense"]
    risk_assessment = node_input  # output from the risk_reviewer node

    # Pause execution if the decision hasn't been submitted yet
    if not ctx.resume_inputs or "approval_decision" not in ctx.resume_inputs:
        msg = (
            f"=== EXPENSE APPROVAL REQUIRED ===\n"
            f"Submitter:   {expense['submitter']}\n"
            f"Amount:      ${expense['amount']:.2f}\n"
            f"Category:    {expense['category']}\n"
            f"Date:        {expense['date']}\n"
            f"Description: {expense['description']}\n\n"
            f"--- LLM Risk Review Findings ---\n"
            f"Alert Level:  {risk_assessment.get('alert_level', 'Unknown')}\n"
            f"Explanation:  {risk_assessment.get('explanation', 'None')}\n"
            f"Risk Factors: {', '.join(risk_assessment.get('risk_factors', []))}\n\n"
            f"Action: Please enter 'Approve' or 'Reject' to record your decision."
        )
        yield RequestInput(interrupt_id="approval_decision", message=msg)
        return

    # Once resumed, retrieve the human response and yield the result
    decision = ctx.resume_inputs["approval_decision"]
    yield Event(
        output={
            "expense": expense,
            "decision": f"Human Review: {decision}",
            "risk_assessment": (
                f"LLM Alert: {risk_assessment.get('alert_level')}. "
                f"Explanation: {risk_assessment.get('explanation')}"
            ),
        }
    )


def record_outcome(node_input: dict):
    """Final node that logs and returns the workflow result."""
    expense = node_input["expense"]
    decision = node_input["decision"]
    risk_assessment = node_input["risk_assessment"]

    summary = (
        f"=== Expense Approval Final Result ===\n"
        f"- Submitter:   {expense['submitter']}\n"
        f"- Amount:      ${expense['amount']:.2f}\n"
        f"- Category:    {expense['category']}\n"
        f"- Date:        {expense['date']}\n"
        f"- Description: {expense['description']}\n"
        f"- Risk Status: {risk_assessment}\n"
        f"- Final Decision: {decision}\n"
    )

    # Yield content event for Web UI rendering
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=summary)])
    )
    # Yield output event as the final return value of the workflow
    yield Event(
        output={
            "status": "completed",
            "expense": expense,
            "decision": decision,
            "risk_assessment": risk_assessment,
            "summary": summary,
        }
    )


# =====================================================================
# Workflow Graph Definition
# =====================================================================

root_agent = Workflow(
    name="expense_approval_workflow",
    edges=[
        ("START", parse_expense),
        (parse_expense, route_expense),
        (
            route_expense,
            {
                "auto_approve": record_outcome,
                "risk_review": security_checkpoint,
            },
        ),
        (
            security_checkpoint,
            {
                "clean_expense": risk_reviewer,
                "security_escalation": human_approval,
            },
        ),
        (risk_reviewer, human_approval),
        (human_approval, record_outcome),
    ],
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
