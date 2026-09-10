# S4 idle fixture oracle amendment

Original artifacts in v4-implementation/progress/run-01 are retained with their failure. The fixture intentionally exits generation 1 without any effect; each subsequent Host prompt starts a new fixture process. Thus len(worker-starts)==1 contradicts the required successful automatic continuation. Independent architecture reviewer confirmed this from source and evidence.

The new regression requires exactly two prompts and starts, generations 1 and 2, identical Task/Session/Attempt/root, exactly one effect only in generation 2, the first explicit nonterminal wait, exactly one accepted completion, and zero rotations. The baseline controller still fails automatic continuation. This amendment changes a contradictory process-count assumption and preserves the no-duplicate-effect requirement. These are synthetic process/HTTP component tests, not real-model or bank acceptance.
