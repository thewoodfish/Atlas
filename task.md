claude "Add final polish to the Atlas project:
- Write pytest tests in tests/ for:
  * Risk manager hard rules (test each constraint)
  * Simulator projection math
  * Wallet balance accounting (deposits/withdrawals always balance)
  * API endpoint responses
- Add a Makefile with: make install, make run-demo, make run-live, make test, make dashboard
- Add docker-compose.yml to run the full stack (api + frontend)
- Update README.md with:
  * Project overview
  * Architecture diagram in ASCII
  * Quick start instructions
  * Demo walkthrough
  * Tech stack table
- Do a final pass: ensure all imports work, no circular dependencies, consistent logging format across all agents"
```

---

## Run Order Summary
```
Step 1  → scaffold
Step 2  → data layer
Step 3-5 → agents
Step 6-7 → core engine
Step 8  → execution
Step 9  → orchestrator
Step 10 → backend API
Step 11 → frontend
Step 12 → entry point
Step 13 → tests + polish