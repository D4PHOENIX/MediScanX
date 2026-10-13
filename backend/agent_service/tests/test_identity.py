import contextlib
import pytest
import uuid
import asyncpg
import json
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import HumanMessage, AIMessage
from fastapi import HTTPException

from app.api.routes import _assert_thread_owned
from app.agent.powersync import sync_state_messages
from app.core.exceptions import AgentBaseException


class FakePool:
    def __init__(self, conn):
        self._conn = conn
    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self._conn

@pytest.fixture
def test_user_id():
    # from auth_headers in conftest
    return "ff46e7d4-df9c-406f-be0c-987537a1b8a3"

# Direct tests for _assert_thread_owned
@pytest.mark.asyncio
async def test_guard_fetchval_true(test_user_id):
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_pool = FakePool(mock_conn)

    thread_id = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await _assert_thread_owned(mock_pool, thread_id, test_user_id)
    assert exc.value.status_code == 403
    
    mock_conn.fetchval.assert_called_once()
    args = mock_conn.fetchval.call_args[0]
    assert "public.chat_messages WHERE thread_id = $1::uuid AND patient_id <> $2::uuid" in args[0]
    assert args[1] == thread_id
    assert args[2] == test_user_id

@pytest.mark.asyncio
async def test_guard_fetchval_false(test_user_id):
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=False)
    mock_pool = FakePool(mock_conn)

    await _assert_thread_owned(mock_pool, str(uuid.uuid4()), test_user_id)
    mock_conn.fetchval.assert_called_once()

@pytest.mark.asyncio
async def test_guard_raises(test_user_id):
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(side_effect=Exception("DB connection dropped"))
    mock_pool = FakePool(mock_conn)

    with pytest.raises(Exception, match="DB connection dropped"):
        await _assert_thread_owned(mock_pool, str(uuid.uuid4()), test_user_id)

# Route-level tests
@pytest.mark.asyncio
async def test_t1_payload_patient_id_mismatch(async_client, auth_headers):
    # payload.patient_id != token user -> 403
    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "patient_id": str(uuid.uuid4())
    })
    assert response.status_code == 403
    assert "patient_id does not match" in response.json()["detail"]

@pytest.mark.asyncio
async def test_t2_empty_payload_patient_id(test_app, async_client, auth_headers, test_user_id):
    # empty payload.patient_id -> allowed; graph state patient_id == token user.
    captured_state = {}
    async def _capture_stream(initial_state, *args, **kwargs):
        captured_state.update(initial_state)
        return
        yield
    test_app.state.graph.astream_events = _capture_stream

    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "patient_id": None
    })
    assert response.status_code == 200
    assert captured_state["patient_id"] == test_user_id

@pytest.mark.asyncio
async def test_t3_thread_id_not_owned(async_client, auth_headers, test_user_id):
    with patch("app.api.routes._assert_thread_owned", new_callable=AsyncMock) as mock_guard:
        mock_guard.side_effect = HTTPException(403, "thread_id not owned by caller")
        response = await async_client.post("/chat", headers=auth_headers, json={
            "messages": [{"role": "user", "content": "hi"}],
            "thread_id": str(uuid.uuid4())
        })
        assert response.status_code == 403
        assert "not owned by caller" in response.json()["detail"]
        mock_guard.assert_called_once()

@pytest.mark.asyncio
async def test_t4_thread_id_another_user(async_client, auth_headers, test_user_id):
    with patch("app.api.routes._assert_thread_owned", new_callable=AsyncMock) as mock_guard:
        mock_guard.side_effect = HTTPException(403, "thread_id not owned by caller")
        target_thread_id = str(uuid.uuid4())
        response = await async_client.post("/chat", headers=auth_headers, json={
            "messages": [{"role": "user", "content": "hi"}],
            "thread_id": target_thread_id
        })
        assert response.status_code == 403
        mock_guard.assert_called_once()

@pytest.mark.asyncio
async def test_t5_valid_owned_thread_id(test_app, async_client, auth_headers, test_user_id):
    with patch("app.api.routes._assert_thread_owned", new_callable=AsyncMock) as mock_guard:
        captured_configs = []
        async def _capture_stream(*args, config=None, **kwargs):
            captured_configs.append(config)
            return
            yield
        test_app.state.graph.astream_events = _capture_stream

        target_thread_id = str(uuid.uuid4())
        response = await async_client.post("/chat", headers=auth_headers, json={
            "messages": [{"role": "user", "content": "hi"}],
            "thread_id": target_thread_id
        })
        assert response.status_code == 200
        mock_guard.assert_called_once()
        assert captured_configs[0]["configurable"]["thread_id"] == target_thread_id

@pytest.mark.asyncio
async def test_t6_thread_id_omitted(test_app, async_client, auth_headers, test_user_id):
    captured_configs = []
    async def _capture_stream(*args, config=None, **kwargs):
        captured_configs.append(config)
        return
        yield
    test_app.state.graph.astream_events = _capture_stream

    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}]
    })
    assert response.status_code == 200
    assert captured_configs[0]["configurable"]["thread_id"] == test_user_id

@pytest.mark.asyncio
async def test_t7_thread_id_is_token_user(test_app, async_client, auth_headers, test_user_id):
    with patch("app.api.routes._assert_thread_owned", new_callable=AsyncMock) as mock_guard:
        async def _empty_stream(*args, **kwargs):
            return
            yield
        test_app.state.graph.astream_events = _empty_stream

        response = await async_client.post("/chat", headers=auth_headers, json={
            "messages": [{"role": "user", "content": "hi"}],
            "thread_id": test_user_id
        })
        assert response.status_code == 200
        mock_guard.assert_not_called()

@pytest.mark.asyncio
async def test_t8_guard_query_raises(async_client, auth_headers, test_user_id):
    with patch("app.api.routes._assert_thread_owned", new_callable=AsyncMock) as mock_guard:
        mock_guard.side_effect = Exception("DB Error")
        with pytest.raises(Exception, match="DB Error"):
            await async_client.post("/chat", headers=auth_headers, json={"messages": [{"role": "user", "content": "hi"}], "thread_id": str(uuid.uuid4())})


@pytest.mark.asyncio
async def test_t9_sync_powersync_missing_patient_id():
    from app.agent.graph import _sync_powersync_node
    with pytest.raises(ValueError, match="sync_powersync: patient_id missing from state"):
        await _sync_powersync_node({"messages": []}, {"configurable": {"thread_id": "1", "db_pool": "1"}})

@pytest.mark.asyncio
async def test_t10_sync_powersync_missing_db_pool():
    from app.agent.graph import _sync_powersync_node
    with pytest.raises(RuntimeError, match="sync_powersync: db_pool missing from config"):
        await _sync_powersync_node({"messages": [], "patient_id": "p"}, {"configurable": {"thread_id": "1"}})
    with pytest.raises(RuntimeError, match="sync_powersync: thread_id missing from config"):
        await _sync_powersync_node({"messages": [], "patient_id": "p"}, {"configurable": {"db_pool": "1"}})

@pytest.mark.asyncio
async def test_t16_sync_powersync_happy_path():
    from app.agent.graph import _sync_powersync_node
    with patch("app.agent.graph.sync_state_messages", new_callable=AsyncMock) as mock_sync:
        await _sync_powersync_node(
            {"messages": [HumanMessage(content="hi")], "patient_id": "p"},
            {"configurable": {"thread_id": "1", "db_pool": "pool1"}}
        )
        mock_sync.assert_awaited_once_with("pool1", "1", "p", [HumanMessage(content="hi")], [])
@pytest.mark.asyncio
async def test_t11_sync_state_messages_fails():
    mock_conn = MagicMock()
    mock_conn.executemany = AsyncMock(side_effect=OSError("Simulated DB failure"))
    mock_pool = FakePool(mock_conn)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(OSError, match="Simulated DB failure"):
            await sync_state_messages(mock_pool, "t", "p", [HumanMessage(content="hi")])
        assert mock_conn.executemany.await_count == 3

@pytest.mark.asyncio
async def test_t12_sync_state_messages_happy_path():
    mock_conn = MagicMock()
    mock_conn.executemany = AsyncMock()
    mock_pool = FakePool(mock_conn)

    await sync_state_messages(mock_pool, "thread_xyz", "patient_abc", [HumanMessage(content="hello")])
    mock_conn.executemany.assert_awaited_once()
    query = mock_conn.executemany.call_args[0][0]
    records = mock_conn.executemany.call_args[0][1]
    assert "INSERT INTO chat_messages" in query
    assert len(records) == 1
    assert records[0][1] == "thread_xyz"
    assert records[0][2] == "patient_abc"

@pytest.mark.asyncio
async def test_t13_sync_powersync_error_reaches_client(test_app, async_client, auth_headers):
    # Exception in sync_powersync reaches client as an SSE error event
    async def _fake_stream(*args, **kwargs):
        raise ValueError("sync_powersync: patient_id missing from state")
        yield
    
    test_app.state.graph.astream_events = _fake_stream

    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "test"}]
    })
    # Stream returns 200 HTTP, but yields error event inside the stream
    assert response.status_code == 200
    content = response.text
    
    found_error = False
    for line in content.split("\n"):
        if line.startswith("data: ") and '"error": true' in line:
            data = json.loads(line[6:])
            assert data["type"] == "UnhandledError"
            assert "sync_powersync: patient_id missing" in data["message"]
            found_error = True
            break
    assert found_error

@pytest.mark.asyncio
async def test_t14_unpatched_guard_not_owned(test_app, async_client, auth_headers):
    # Set AFTER lifespan startup
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=True)
    test_app.state.db_pool = FakePool(mock_conn)
    
    test_app.state.graph.astream_events = MagicMock()
    
    target_thread_id = str(uuid.uuid4())
    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "thread_id": target_thread_id
    })
    assert response.status_code == 403
    assert "thread_id not owned by caller" in response.json()["detail"]
    test_app.state.graph.astream_events.assert_not_called()

@pytest.mark.asyncio
async def test_t15_unpatched_guard_owned(test_app, async_client, auth_headers):
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=False)
    test_app.state.db_pool = FakePool(mock_conn)
    
    captured_configs = []
    async def _capture_stream(*args, config=None, **kwargs):
        captured_configs.append(config)
        return
        yield
    test_app.state.graph.astream_events = _capture_stream

    target_thread_id = str(uuid.uuid4())
    response = await async_client.post("/chat", headers=auth_headers, json={
        "messages": [{"role": "user", "content": "hi"}],
        "thread_id": target_thread_id
    })
    assert response.status_code == 200
    assert captured_configs[0]["configurable"]["thread_id"] == target_thread_id

@pytest.mark.asyncio
async def test_t17_sync_message_text_extraction():
    mock_conn = MagicMock()
    mock_conn.executemany = AsyncMock()
    mock_pool = FakePool(mock_conn)

    # 1. str -> unchanged
    await sync_state_messages(mock_pool, "t", "p", [HumanMessage(content="hello")])
    assert mock_conn.executemany.call_args[0][1][0][4] == "hello"
    mock_conn.executemany.reset_mock()

    # 2. list with text blocks -> plain joined text
    content_list = [
        {"type": "text", "text": "block1 "},
        "plain_string ",
        {"type": "image_url", "image_url": "foo"},
        {"type": "text", "text": "block2"}
    ]
    await sync_state_messages(mock_pool, "t", "p", [HumanMessage(content=content_list)])
    assert mock_conn.executemany.call_args[0][1][0][4] == "block1 plain_string block2"
    mock_conn.executemany.reset_mock()

    # 3. list with only non-text blocks -> AI row skipped (since text is empty)
    content_list_non_text = [{"type": "image_url", "image_url": "foo"}]
    await sync_state_messages(mock_pool, "t", "p", [AIMessage(content=content_list_non_text)])
    mock_conn.executemany.assert_not_called()

    # 4. an int -> TypeError
    with pytest.raises(TypeError):
        await sync_state_messages(mock_pool, "t", "p", [HumanMessage.construct(content=123)])

@pytest.mark.asyncio
async def test_t18_sync_state_messages_clock_timestamp():
    mock_conn = MagicMock()
    mock_conn.executemany = AsyncMock()
    mock_pool = FakePool(mock_conn)

    await sync_state_messages(mock_pool, "t", "p", [HumanMessage(content="hello")])
    query = mock_conn.executemany.call_args[0][0]
    assert "clock_timestamp()" in query
    assert "NOW()" not in query
