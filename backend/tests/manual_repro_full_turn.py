import sys, traceback
sys.path.insert(0, ".")
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path("..") / ".env")

from datetime import datetime
from app.agent.orchestrator import run_agent_turn

db_path = "../data/parcelpilot.db"
index_path = "../data/doc_index.pkl"
actions_db_path = "../data/actions.db"
reference_time = datetime(2026, 8, 16, 11, 0)

print("=== TURN 1 ===")
try:
    turn1 = run_agent_turn(
        "manager_priya",
        [{"role": "user", "content": "TKT-501 says Northstar can't create any shipments. What's going on and what should we do?"}],
        db_path, index_path, reference_time,
        actions_db_path=actions_db_path,
    )
    print("Turn 1 response:", turn1["response"][:200])
    print("Turn 1 tool_trace tools used:", [t["tool"] for t in turn1["tool_trace"]])
except Exception:
    print("TURN 1 CRASHED:")
    traceback.print_exc()
    sys.exit(1)

print()
print("=== TURN 2 (this is where it breaks in the real app) ===")
conversation_turn2 = [
    {"role": "user", "content": "TKT-501 says Northstar can't create any shipments. What's going on and what should we do?"},
    {"role": "assistant", "content": turn1["response"]},
    {"role": "user", "content": "Yes, please prepare the escalation"},
]
try:
    turn2 = run_agent_turn("manager_priya", conversation_turn2, db_path, index_path, reference_time,
                           actions_db_path=actions_db_path)
    print("Turn 2 response:", turn2["response"])
    print("Turn 2 tool_trace:", turn2["tool_trace"])
except Exception:
    print("TURN 2 CRASHED:")
    traceback.print_exc()
