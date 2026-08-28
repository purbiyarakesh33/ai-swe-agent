from agents.agent1_understanding import investigate
from agents.agent2_planning import create_plan

issue = "the records library isn't behaving correctly, something seems off"

result1 = investigate("./records", issue)
print("--- AGENT 1 ---")
print(result1)

plan = create_plan("./records", issue, result1["investigation_notes"])
print("\n--- AGENT 2 PLAN ---")
print(plan)

