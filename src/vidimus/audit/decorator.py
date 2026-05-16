"""User-facing instrumentation: ``@vidimus.audit`` and ``with vidimus.trace()``."""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

from vidimus.audit.schemas import Span, Trace
from vidimus.config import get_config

F = TypeVar("F", bound=Callable[..., Any])


def audit(func: F | None = None, *, name: str | None = None) -> F | Callable[[F], F]:
    """Decorate a function so each invocation is captured as a Vidimus trace.

    Usage:

        @vidimus.audit
        def my_agent(query: str) -> str:
            return "..."

        # Or with a custom name:
        @vidimus.audit(name="customer_support_agent")
        def handle(q: str) -> str:
            ...

    The decorator records the function's argument values, return value,
    execution time, and exceptions into a Trace that is appended to the
    active store.
    """

    def _wrap(f: F) -> F:
        trace_name = name or f.__qualname__

        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            config = get_config()
            start_ns = time.time_ns()
            input_repr = _arg_repr(args, kwargs)
            status = "ok"
            output: Any = None
            try:
                output = f(*args, **kwargs)
                return output
            except Exception:
                status = "error"
                raise
            finally:
                end_ns = time.time_ns()
                span = Span(
                    parent_span_id=None,
                    name=trace_name,
                    start_ns=start_ns,
                    end_ns=end_ns,
                    attributes={},
                    status=status,  # type: ignore[arg-type]
                )
                trace = Trace(
                    workspace=config.workspace,
                    spans=[span],
                    input=input_repr,
                    output=_value_repr(output),
                )
                config.store.add_trace(trace)

        return wrapper  # type: ignore[return-value]

    if func is None:
        return _wrap
    return _wrap(func)


class _TraceCtx:
    """Context manager handle returned by ``vidimus.trace()``."""

    def __init__(self, name: str):
        self._name = name
        self._start_ns = time.time_ns()
        self._input: Any = ""
        self._output: Any = ""
        self._metadata: dict[str, Any] = {}
        self._status: str = "ok"

    def set_input(self, value: Any) -> None:
        self._input = _value_repr(value)

    def set_output(self, value: Any) -> None:
        self._output = _value_repr(value)

    def set_metadata(self, **kwargs: Any) -> None:
        self._metadata.update(kwargs)

    def _build_trace(self) -> Trace:
        config = get_config()
        end_ns = time.time_ns()
        span = Span(
            parent_span_id=None,
            name=self._name,
            start_ns=self._start_ns,
            end_ns=end_ns,
            attributes={},
            status=self._status,  # type: ignore[arg-type]
        )
        return Trace(
            workspace=config.workspace,
            spans=[span],
            input=self._input,
            output=self._output,
            metadata=self._metadata,
        )


@contextmanager
def trace(name: str) -> Iterator[_TraceCtx]:
    """Manually open a trace block.

    Usage:

        with vidimus.trace(name="custom_op") as t:
            t.set_input(query)
            result = do_work(query)
            t.set_output(result)
            t.set_metadata(model="gpt-4o", cost_usd=0.01)
    """
    ctx = _TraceCtx(name=name)
    try:
        yield ctx
    except Exception:
        ctx._status = "error"
        raise
    finally:
        config = get_config()
        config.store.add_trace(ctx._build_trace())


def _arg_repr(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [repr(a) for a in args]
    parts.extend(f"{k}={v!r}" for k, v in kwargs.items())
    out = ", ".join(parts)
    return out[:2000] if len(out) > 2000 else out


def _value_repr(value: Any) -> str | dict[str, Any]:
    if isinstance(value, (dict, str)):
        if isinstance(value, str) and len(value) > 2000:
            return value[:2000] + "...[truncated]"
        return value
    out = repr(value)
    return out[:2000] if len(out) > 2000 else out
