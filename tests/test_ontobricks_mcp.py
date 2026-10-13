import pytest

from server.ontobricks import OntoBricksError, _graphql, _normalize_text


@pytest.mark.parametrize(
    ("intent", "expected_relation"),
    [
        ("CUSTOMER_RELATIONSHIPS", "qualifiedContact"),
        ("PLAN_ELIGIBILITY", "subscribedTo"),
        ("SLA_CONTEXT", "governedBySLA"),
        ("RECOMMENDATION_CONTEXT", "recommendedProduct"),
        ("CUSTOMER_CONTEXT", "memberOfRelationshipGroup"),
    ],
)
def test_customer_intents_are_anchored_and_never_use_global_plural(intent, expected_relation):
    query, _, _ = _graphql(intent, None, "CLI-123", 20)
    assert 'customer(id: "CLI-123")' in query
    assert expected_relation in query
    assert "customers(limit:" not in query
    assert "qualifiedContacts(limit:" not in query
    assert "plans(limit:" not in query
    assert "sLAs(limit:" not in query


def test_scoped_class_navigation_rejects_unreachable_reverse_class():
    with pytest.raises(OntoBricksError, match="navegación territorial segura"):
        _graphql("CLASS_MEMBERS", "Recommendation", "CLI-123", 20)


def test_mcp_text_repairs_utf8_transport_artifact():
    assert _normalize_text("GraphQL Result â Quetzal") == "GraphQL Result — Quetzal"
