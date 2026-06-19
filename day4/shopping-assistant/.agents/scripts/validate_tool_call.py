import sys
import json
import re

def main():
    try:
        # Read the full JSON context from stdin
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({"decision": "allow"}))
            return

        context = json.loads(input_data)

        # Extract the command from toolCall.args.CommandLine
        tool_call = context.get("toolCall", {})
        args = tool_call.get("args", {})
        command = args.get("CommandLine", "")

        # Check for destructive patterns
        destructive_patterns = [
            r"rm\s+-[a-zA-Z]*rf",          # e.g., rm -rf, rm -fr
            r"rm\s+--recursive\s+--force", # e.g., rm --recursive --force
            r"del\s+.*\/f.*\/q",           # Windows force/quiet delete
            r"rd\s+.*\/s.*\/q",            # Windows force/quiet directory remove
        ]

        is_destructive = False
        for pattern in destructive_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                is_destructive = True
                break

        if is_destructive:
            print(json.dumps({"decision": "deny"}))
        else:
            print(json.dumps({"decision": "allow"}))

    except Exception:
        # Fail-closed in case of parsing/execution errors
        print(json.dumps({"decision": "deny"}))

if __name__ == "__main__":
    main()
