# STRIDE Threat Model Assessment: Shopping Assistant Agent

This document details the threat modeling assessment of the **Shopping Assistant Agent** codebase and architecture based on the STRIDE framework.

## 1. System Boundaries & Data Flow Diagram (DFD)

The system consists of the following boundaries and components:
*   **User/Customer**: Interacts with the agent via CLI, Playground web server, or Google Gemini Enterprise.
*   **Agent (LlmAgent)**: Configured in `app/agent.py`. It orchestrates interactions, processes natural language, and uses registered tools.
*   **Tools**: Python functions (e.g., `redeem_discount_code`) that execute business logic.
*   **Storage/State**: In-memory state tracking (`REDEEMED_DISCOUNT_CODES`, `REGISTERED_USERS`).
*   **External APIs**: Vertex AI Gemini API endpoint for model reasoning.
*   **Gatekeeping / Hooks**: Local hooks (`.agents/hooks.json`, `.agents/scripts/validate_tool_call.py`) and pre-commit scans.

---

## 2. STRIDE Assessment

### Spoofing (Identity)
*   **Threat**: An attacker could spoof a registered user ID (e.g., `user123`) to redeem discount codes belonging to others or bypass registration checks.
*   **Analysis**: The `redeem_discount_code` function accepts `user_id` directly as an argument without cryptographic signature or token verification.
*   **Mitigation**: Implement authentication/authorization checks (e.g., JWT validation or OAuth token check) in `agent_runtime_app.py` or the tool rather than accepting raw user IDs.

### Tampering (Data Integrity)
*   **Threat**: Local in-memory state or tool results could be tampered with.
*   **Analysis**: `REDEEMED_DISCOUNT_CODES` is in-memory. If the server restarts, state is lost. An attacker could exploit server crashes/restarts to double-redeem codes.
*   **Mitigation**: Persist state to a secure database (e.g., Firestore, Cloud SQL) with transactional integrity.

### Repudiation (Non-repudiation)
*   **Threat**: A user claims they never made a transaction/redemption.
*   **Analysis**: Telemetry is set up via OpenTelemetry and Cloud Logging in `agent_runtime_app.py`. However, audit logging for specific tool execution success/failure must be cryptographically signed or stored in read-only write-once-read-many (WORM) storage.
*   **Mitigation**: Ensure all tool executions write to structured audit logs in Google Cloud Logging with appropriate retention policies.

### Information Disclosure (Confidentiality)
*   **Threat**: Hardcoded API keys or sensitive customer details could be disclosed.
*   **Analysis**: A hardcoded mock key `AIzaSyD-mock-key-value-12345` was detected by our Semgrep rule. Hardcoding keys poses a severe leak risk in public repositories.
*   **Mitigation**: Enforce the use of environment variables or Google Secret Manager. Use the Semgrep pre-commit hook to block secret leaks.

### Denial of Service (Availability)
*   **Threat**: Attacker exhausts the Gemini API quota or causes server resource exhaustion.
*   **Analysis**: There are no rate limits on the local playground or API integrations. Prompt injection could trick the LLM into infinite loops.
*   **Mitigation**: Implement rate limiting, session size limits, and max token limits on Vertex AI completions.

### Elevation of Privilege (Authorization)
*   **Threat**: The agent runs arbitrary destructive commands.
*   **Analysis**: The `run_command` tool allows terminal execution. If the agent is hijacked, it could execute dangerous commands.
*   **Mitigation**: The `PreToolUse` hook in `.agents/hooks.json` intercepts `run_command` and runs `validate_tool_call.py` to block destructive commands like `rm -rf`. Further restrict the agent execution environment (sandbox/containers) and enforce least privilege IAM roles.

---

## 3. Risk Summary & Action Items

| Pillar | Threat | Severity | Action Item |
|---|---|---|---|
| **S** | Spoofing registered user ID | High | Integrate authentication/verification of `user_id` |
| **T** | In-memory state loss / double redemption | Medium | Implement persistent DB storage |
| **R** | Audit trail repudiation | Low | Standardize structured tool usage logs |
| **I** | Leak of credentials | Critical | Remove any hardcoded keys, use Secret Manager |
| **D** | LLM resource exhaustion / prompt injection | Medium | Set maximum token limits and rate limits |
| **E** | Arbitrary code execution | High | Sandbox the agent, enforce `PreToolUse` hooks |
