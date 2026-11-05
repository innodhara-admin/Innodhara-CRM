"""The ten AI engines (30-Workflows doc §4).

Each engine has one job, its own triggers, and its own tables:

1.  Planner      — versioned global action plans, merges, feasibility, conflicts
2.  Assignment   — picks the best person for every task, with a written reason
3.  Resource     — the single owner of "who and what is free when"
4.  Sync         — the heartbeat: reacts to every event + a daily sweep
5.  Communication— drafts every outward message; never sends on its own
6.  Document     — builds every artifact; accepts manual uploads as equals
7.  Inbound      — reads every incoming message; nothing is ever dropped
8.  Approval     — finds the right approver; records every decision
9.  Knowledge    — the organisation's memory and playbook learning
10. Assistant    — the front door for everything a person types or says

Three rules stand above all ten (enforced across the codebase):
- Nothing reaches the school without a human approval (ai_decisions records why).
- People can always do the work themselves; engines reconcile manual work.
- When the AI is unsure, it asks a named human — it never guesses.
"""
