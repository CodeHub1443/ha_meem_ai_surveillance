# Architecture Lock

All structural or architectural changes must be explicitly instructed by human.

Agent may only:
- Implement small modules
- Refactor within file
- Fix bugs

Agent may NOT:
- Add new subsystems
- Add new frameworks
- Add new dependencies
- Modify folder structure
- Introduce training logic
- Introduce ClearML into runtime

All major decisions must be approved first.