from rc8_node.code_sufficiency_worker import CodeSufficiencyPolicy


def test_code_sufficiency_requires_graph_backed_complete_analysis():
    observation = CodeSufficiencyPolicy.evaluate(
        "artifact-1",
        {
            "changed_files": ["src/A.java"],
            "graph_evidence": [{"query": "callers", "result": ["B"]}],
            "sufficiency": {"sufficient": True, "unresolved": []},
        },
    )
    assert observation.sufficient is True
    assert observation.missing == ()
    assert observation.as_dict()["authority"] == "NODE_OBSERVATION_ONLY"


def test_code_sufficiency_fails_closed_without_codegraph_evidence():
    observation = CodeSufficiencyPolicy.evaluate(
        "artifact-2",
        {
            "changed_files": ["src/A.java"],
            "graph_evidence": [],
            "sufficiency": {"sufficient": True, "unresolved": []},
        },
    )
    assert observation.sufficient is False
    assert "graph_evidence:non-empty" in observation.missing


def test_code_sufficiency_fails_closed_on_unresolved_analysis_gaps():
    observation = CodeSufficiencyPolicy.evaluate(
        "artifact-3",
        {
            "changed_files": ["src/A.java"],
            "graph_evidence": [{"query": "dependencies"}],
            "sufficiency": {"sufficient": False, "unresolved": ["unknown caller"]},
        },
    )
    assert observation.sufficient is False
    assert "sufficiency:sufficient=true" in observation.missing
    assert "sufficiency:unresolved-empty" in observation.missing
