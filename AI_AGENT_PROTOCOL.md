# AI Agent Protocol: The Mandatory Doorstep

**ATTENTION ALL AI AGENTS (Jules, Codex, Claude, Grok, etc.)**
This protocol is a mandatory technical guardrail that **every AI agent must go through before making any code change** to the project. It acts as a secure "doorstep" checkpoint to prevent context washout, careless edits, and untracked changes.

There is NO visible UI tab for this protocol. It is an internal development requirement.

---

## Detailed Code Change Checklist (Anti Context-Washout)

Before proposing or making any changes, you must explicitly address and confirm the following internally (or in your response):

1. **Full Context Review**
   - I have read the entire relevant file(s) and key surrounding modules.
   - I have reviewed the current branch and recent commit history (if applicable).

2. **Requirement Fidelity**
   - The change strictly follows the user's exact request.
   - No unsolicited features or deviations.

3. **Context Continuity Check**
   - I am not experiencing context washout. I retain all previous conversation history and instructions.
   - I have cross-referenced earlier decisions and code patterns.

4. **Impact Analysis**
   - Effects on authentication, session state, performance, security, and other modules evaluated.
   - Backward compatibility and breaking changes considered.

5. **Security & Quality**
   - No security regressions, no hardcoded secrets, proper validation and error handling.
   - Changes are minimal and reversible where possible.

6. **Testing & Validation**
   - Mentally simulated the change + edge cases.
   - Follows existing Streamlit patterns and style.

7. **Documentation & Logging**
   - Will provide clear explanation of what, why, and how.

---

## Change Logging & Audit Trail

For **every change** made by an AI agent, you must log it. We use a file-based JSON Lines log located at `logs/ai_audit_log.jsonl`.
Use the helper functions provided in `engine/utils/ai_audit.py` to append the log.
If making changes outside the Python environment (e.g., via bash), manually append a JSON object matching the format below.

### AI Change Template (Required Fields)

When logging a change, the following structure is required:

```json
{
  "timestamp": "2023-10-27T10:00:00+05:30",  // IST timezone
  "agent": "Jules",                            // Your AI name
  "files_changed": ["streamlit_app.py", "engine/utils/db.py"],
  "summary": "Added new feature X as requested.",
  "reason": "User requested feature X to solve problem Y.",
  "commit_message": "feat: Added feature X", // Expected or current commit title
  "status": "Checklist Confirmed"            // Confirming the checklist was followed
}
```

## Protocol Enforcement

Whenever you modify key files (like `streamlit_app.py`, `engine/utils/db.py`, etc.), ensure the top-of-file documentation retains a reference to this `AI_AGENT_PROTOCOL.md`.
