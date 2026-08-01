from __future__ import annotations

from typing import Any

from schemas.catalog import Catalog, Mapping, Operation, StepDefinition, ToolCall
from utils import CatalogLookupError, OperationArgumentError, matches_declared_type


class OperationLoader:
    """Lookups over steps, operations, and mappings — and the binding between them.

    `resolve_call` is the whole point: it turns "run operation X with these
    parameters" into a concrete tool call, applying the domain's argument
    bindings. Nothing else in the runtime should know a tool name.
    """

    def __init__(self, catalog: Catalog) -> None:
        self._steps = {step.name: step for step in catalog.steps}
        self._operations = {operation.name: operation for operation in catalog.operations}
        self._mappings = {mapping.operation: mapping for mapping in catalog.mappings}

    def get_step(self, name: str) -> StepDefinition:
        try:
            return self._steps[name]
        except KeyError:
            known = ", ".join(sorted(self._steps)) or "none"
            raise CatalogLookupError(
                f"unknown step '{name}' (catalog has: {known})"
            ) from None

    def get_operation(self, name: str) -> Operation:
        try:
            return self._operations[name]
        except KeyError:
            known = ", ".join(sorted(self._operations)) or "none"
            raise CatalogLookupError(
                f"unknown operation '{name}' (catalog has: {known})"
            ) from None

    def get_mapping(self, operation: str) -> Mapping:
        try:
            return self._mappings[operation]
        except KeyError:
            raise CatalogLookupError(
                f"operation '{operation}' has no tool mapping"
            ) from None

    def resolve_call(
        self,
        operation: str,
        parameters: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> ToolCall:
        """Bind declared parameters and trusted context into a tool call."""
        declared = self.get_operation(operation)
        mapping = self.get_mapping(operation)
        resolved = self._resolve_parameters(declared, parameters or {})

        arguments: dict[str, Any] = {}
        for argument, source in mapping.arguments.items():
            kind, _, name = source.partition(".")

            if kind == "param":
                # An absent optional parameter is simply not sent, so the tool
                # applies its own default rather than receiving a null.
                if name in resolved and resolved[name] is not None:
                    arguments[argument] = resolved[name]

            elif kind == "context":
                if context is None or name not in context:
                    raise OperationArgumentError(
                        f"{operation}: missing runtime context '{name}' required by "
                        f"tool argument '{argument}'"
                    )
                value = context[name]
                if value is not None:
                    arguments[argument] = value

            elif kind == "const":
                arguments[argument] = name

            else:
                raise OperationArgumentError(
                    f"{operation}: tool argument '{argument}' has unusable binding "
                    f"'{source}'"
                )

        return ToolCall(
            operation=operation,
            server=mapping.server,
            tool=mapping.tool,
            arguments=arguments,
            destructive=mapping.destructive,
            requires_approval=mapping.requires_approval,
        )

    @staticmethod
    def _resolve_parameters(
        operation: Operation, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        unknown = sorted(set(parameters) - set(operation.parameters))
        if unknown:
            raise OperationArgumentError(
                f"{operation.name}: undeclared parameters {unknown}"
            )

        resolved: dict[str, Any] = {}
        for name, declared in operation.parameters.items():
            if name in parameters and parameters[name] is not None:
                value = parameters[name]
            elif declared.required:
                raise OperationArgumentError(
                    f"{operation.name}: missing required parameter '{name}'"
                )
            else:
                # A declared default is part of the contract, so send it
                # explicitly rather than relying on the tool to agree.
                if declared.default is None:
                    continue
                value = declared.default

            if not matches_declared_type(value, declared.type):
                raise OperationArgumentError(
                    f"{operation.name}: parameter '{name}' expects {declared.type}, "
                    f"got {type(value).__name__}"
                )
            if declared.enum is not None and value not in declared.enum:
                raise OperationArgumentError(
                    f"{operation.name}: parameter '{name}' must be one of "
                    f"{declared.enum}, got {value!r}"
                )

            resolved[name] = value

        return resolved
