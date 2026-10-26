## ADDED Requirements

### Requirement: Luna decisions are strictly typed
The decision client, endpoints, protocols, service, visual checks and pacing SHALL be strict TypeScript checked by
`npm run typecheck`. A decision result SHALL be typed so that its answers cannot be read before its fallback is handled.
Converting them SHALL NOT change what any function returns or sends.

#### Scenario: Reading answers without handling a fallback
- **WHEN** strict code reads `result.answers.finished` from a decision result without first checking `result.fallback`
- **THEN** `tsc` fails

#### Scenario: Same behaviour after the move
- **WHEN** the unit tests for decisions, pacing, visual checks, routing and the studio run against the `.ts` modules
- **THEN** they pass unchanged
