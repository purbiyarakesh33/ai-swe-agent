from agents.agent1_understanding import investigate

result = investigate("./records", "there is some issue in RecordCollection function")
print(result)


from agents.agent2_planning import create_plan


if result["issue_real"]:
    plan = create_plan("./records", "there is some issue in RecordCollection function", result["investigation_notes"])
    print(plan)
else:
    print("Agent 1 didn't confirm the issue — skipping Agent 2.")



