import json
import logging

from workgraph_observability import (
    bind_trace_id,
    configure_logging,
    get_trace_id,
    new_trace_id,
)


def test_trace_id_roundtrip():
    tid = new_trace_id()
    bind_trace_id(tid)
    assert get_trace_id() == tid
    bind_trace_id(None)
    assert get_trace_id() is None


def test_structured_log_emits_trace_id(capsys):
    configure_logging("INFO")
    tid = new_trace_id()
    bind_trace_id(tid)
    try:
        logging.getLogger("t").info("hello", extra={"foo": "bar"})
    finally:
        bind_trace_id(None)
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert payload["level"] == "INFO"
    assert payload["msg"] == "hello"
    assert payload["trace_id"] == tid
    assert payload["extra"] == {"foo": "bar"}


def test_log_without_trace_id_omits_field(capsys):
    configure_logging("INFO")
    bind_trace_id(None)
    logging.getLogger("t").info("no-trace")
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert "trace_id" not in payload
