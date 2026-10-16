from app.services.interpreter import _interpret_prompt_rules


def test_rule_interpreter_extracts_supported_workbench_fields():
    result = _interpret_prompt_rules(
        "Build 4 workbenches, each 1200 x 600 x 850 mm, S275JR mild steel, 3 mm plate. Project DEMO-PROJECT."
    )
    assert result.product_type == "workbench_panel_kit"
    assert result.quantity == 4
    assert (result.length_mm, result.width_mm, result.height_mm) == (1200.0, 600.0, 850.0)
    assert result.material_grade == "S275JR"
    assert result.thickness_mm == 3.0
    assert result.interpreter_mode == "deterministic_rules"
    assert not result.missing_questions


def test_rule_interpreter_does_not_invent_missing_specs():
    result = _interpret_prompt_rules("Build a metal storage product for our customer")
    assert result.product_type is None
    assert result.quantity is None
    assert result.material_grade is None
    assert result.confidence == "low"
    assert len(result.missing_questions) >= 4
