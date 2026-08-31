import pytest

def test_schemas_validation(auth_headers) -> None:
    """Verify strict Pydantic V2 schemas enforce type constraints."""
    from app.models.schemas import RoleMessage, ChatRequest, Citation

    # Valid role
    msg = RoleMessage(role="user", content="Hello")
    assert msg.role == "user"

    # Invalid role must raise
    with pytest.raises(Exception):
        RoleMessage(role="invalid_role", content="test")

    # Citation bounds
    cite = Citation(
        document_id="doc-1",
        title="Test",
        content_excerpt="excerpt",
        similarity_score=0.95,
    )
    assert cite.similarity_score == 0.95

    # similarity_score out of bounds
    with pytest.raises(Exception):
        Citation(
            document_id="doc-2",
            title="Test",
            content_excerpt="excerpt",
            similarity_score=1.5,
        )
