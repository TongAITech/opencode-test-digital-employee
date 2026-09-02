# Mission Runtime Protocol

The authoritative sequence is Mission → frozen Plan version → current Step cursor → Capability Broker → Evidence → Evaluator → state transition.

- `continue` reads the existing Mission and returns RESUME/WAIT_FOR_HUMAN/BLOCKED/WAIT_FOR_H3/WAIT_FOR_H4. It never submits a Plan.
- Replanning is explicit, auditable and creates a new Plan version.
- Worker Sessions are disposable. Checkpoints and Context Packs are reconstructed from Runtime state.
- H1 validates requirement truth; H2 validates design/showcase when required; H3 authorizes real execution against a frozen baseline; H4 accepts the result.
