from src.council.value_axes import (
    AGENT_MANIFEST_VALUE_AXES_SCHEMA,
    ValueAxes,
    validate_value_axes,
)


def test_value_axes_generates_manifest_fragment_and_korean_bias():
    axes = ValueAxes(
        time_horizon="long",
        risk_tolerance=0.72,
        stakeholder_priority=["primary", "tertiary", "secondary"],
        innovation_orientation=0.28,
    )

    assert axes.to_manifest_fragment() == {
        "time_horizon": "long",
        "risk_tolerance": 0.72,
        "stakeholder_priority": ["primary", "tertiary", "secondary"],
        "innovation_orientation": 0.28,
    }
    bias = axes.to_perspective_bias()
    assert "장기 복리 효과" in bias
    assert "높은 불확실성" in bias
    assert "1차 사용자/고객 > 사회/규제/장기 생태계 > 운영자/파트너" in bias
    assert "기존 운영 방식" in bias


def test_value_axes_from_mapping_and_schema_fragment_shape():
    axes = ValueAxes.from_mapping(
        {
            "time_horizon": "mid",
            "risk_tolerance": 0.5,
            "stakeholder_priority": ["secondary"],
            "innovation_orientation": 1,
        }
    )

    assert axes.time_horizon == "mid"
    assert axes.innovation_orientation == 1.0
    schema = ValueAxes.schema_property()
    assert schema == AGENT_MANIFEST_VALUE_AXES_SCHEMA
    assert schema["properties"]["time_horizon"]["enum"] == ["long", "mid", "short"]
    assert schema["properties"]["risk_tolerance"]["minimum"] == 0.0
    assert schema["properties"]["innovation_orientation"]["maximum"] == 1.0


def test_validate_value_axes_reports_schema_like_errors():
    errors = validate_value_axes(
        {
            "time_horizon": "immediate",
            "risk_tolerance": 1.2,
            "stakeholder_priority": ["primary", "unknown"],
            "innovation_orientation": False,
        }
    )

    assert "value_axes.time_horizon must be one of short, mid, long" in errors
    assert "value_axes.risk_tolerance must be between 0.0 and 1.0" in errors
    assert "value_axes.stakeholder_priority[1] must be one of primary, secondary, tertiary" in errors
    assert "value_axes.innovation_orientation must be a number" in errors


def test_value_axes_constructor_fails_closed():
    try:
        ValueAxes(
            time_horizon="short",
            risk_tolerance=-0.1,
            stakeholder_priority=["primary"],
            innovation_orientation=0.3,
        )
    except ValueError as exc:
        assert "value_axes.risk_tolerance must be between 0.0 and 1.0" in str(exc)
    else:
        raise AssertionError("invalid risk_tolerance should raise ValueError")
