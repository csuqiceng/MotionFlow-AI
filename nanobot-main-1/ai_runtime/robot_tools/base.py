"""Small SDK-neutral base class for runtime robot tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any, Callable, TypeVar


_ToolT = TypeVar("_ToolT", bound="Tool")


class Tool(ABC):
    """Duck-typed tool surface accepted by the current agent registry."""

    config_key: str = ""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        ...

    @property
    def read_only(self) -> bool:
        return False

    @property
    def concurrency_safe(self) -> bool:
        """Match Nanobot's tool concurrency contract for runner batching."""
        return self.read_only and not self.exclusive

    @property
    def exclusive(self) -> bool:
        return False

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return True

    @classmethod
    def create(cls, ctx: Any) -> "Tool":
        return cls()

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        return dict(params)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]
        schema = self.parameters
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        errors: list[str] = []
        for key in required:
            if key not in params:
                errors.append(f"missing required {key}")
        for key, value in params.items():
            spec = properties.get(key)
            if not isinstance(spec, dict):
                continue
            if "enum" in spec and value not in spec["enum"]:
                errors.append(f"{key} must be one of {spec['enum']}")
        return errors

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        ...


def tool_parameters(schema: dict[str, Any]) -> Callable[[type[_ToolT]], type[_ToolT]]:
    """Attach a copy-on-read JSON schema to a runtime Tool class."""
    frozen = deepcopy(schema)

    def decorator(cls: type[_ToolT]) -> type[_ToolT]:
        @property
        def parameters(self: Any) -> dict[str, Any]:
            return deepcopy(frozen)

        cls.parameters = parameters  # type: ignore[assignment]
        abstract = getattr(cls, "__abstractmethods__", None)
        if abstract is not None and "parameters" in abstract:
            cls.__abstractmethods__ = frozenset(abstract - {"parameters"})  # type: ignore[misc]
        return cls

    return decorator
