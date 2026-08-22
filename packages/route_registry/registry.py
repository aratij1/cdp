from __future__ import annotations

from pathlib import Path

import yaml

from packages.route_registry.models import RouteDefinition, RouteLifecycle


DEFAULT_ROUTE_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "ocr_field_routes.yaml"
)


class RouteRegistryUnavailableError(RuntimeError):
    pass


class RouteNotApprovedError(RuntimeError):
    pass


class RouteRegistry:
    def __init__(self, *, version: str, routes: list[RouteDefinition]) -> None:
        self.version = version
        self.routes = tuple(routes)
        route_ids = [route.route_id for route in routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("duplicate route_id in route registry")

    @classmethod
    def load(cls, path: str | Path = DEFAULT_ROUTE_REGISTRY_PATH) -> "RouteRegistry":
        try:
            payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        except OSError as exc:
            raise RouteRegistryUnavailableError(f"route registry unavailable: {path}") from exc
        specs = payload.get("ocr_routes")
        if not isinstance(specs, dict):
            raise RouteRegistryUnavailableError("route registry has no ocr_routes mapping")
        routes = []
        for field_name, spec in specs.items():
            if not isinstance(spec, dict):
                raise ValueError(f"invalid route specification: {field_name}")
            routes.append(RouteDefinition(
                route_id=spec["route_id"],
                field=spec["field"],
                form=spec["form"],
                primary_engine=spec["primary_engine"],
                confirmation_engine=spec["confirmation_engine"],
                preprocessing_profile=spec["preprocessing_profile"],
                policy_version=spec["policy_version"],
                benchmark_dataset=spec["benchmark_dataset"],
                sample_count=spec["sample_count"],
                standalone_accuracy=spec.get("standalone_accuracy"),
                agreement_precision=spec.get("agreement_precision"),
                false_agreement_count=spec["false_agreement_count"],
                mean_latency_ms=spec.get("mean_latency_ms"),
                cost_per_call_usd=spec.get("cost_per_call_usd"),
                cost_status=spec["cost_status"],
                status=spec["status"],
                approved_by=spec.get("approved_by"),
                approved_at=spec.get("approved_at"),
                approval_scope=spec.get("approval_scope"),
            ))
            if routes[-1].field != field_name:
                raise ValueError(
                    f"route key/field mismatch: {field_name} != {routes[-1].field}"
                )
        return cls(version=str(payload["version"]), routes=routes)

    def routes_for_mode(self, mode: str) -> tuple[RouteDefinition, ...]:
        if mode == "runtime":
            states = {RouteLifecycle.PRODUCTION_APPROVED}
        elif mode == "evaluation":
            states = {
                RouteLifecycle.EXPERIMENTAL,
                RouteLifecycle.EVALUATION_ONLY,
                RouteLifecycle.SHADOW,
                RouteLifecycle.PRODUCTION_APPROVED,
            }
        elif mode == "shadow":
            states = {RouteLifecycle.SHADOW}
        else:
            raise ValueError("route mode must be runtime, evaluation, or shadow")
        return tuple(route for route in self.routes if route.status in states)

    def find(
        self, field: str, document_family: str, *, mode: str,
    ) -> RouteDefinition | None:
        return next((
            route for route in self.routes_for_mode(mode)
            if route.field == field and route.applies_to(document_family)
        ), None)

    def find_any(self, field: str, document_family: str) -> RouteDefinition | None:
        """Return matching route metadata without granting execution authority."""
        return next((
            route for route in self.routes
            if route.field == field and route.applies_to(document_family)
        ), None)

    def require(
        self, route_id: str, *, mode: str,
    ) -> RouteDefinition:
        route = next((item for item in self.routes if item.route_id == route_id), None)
        if route is None:
            raise RouteNotApprovedError(f"unknown route: {route_id}")
        if route not in self.routes_for_mode(mode):
            raise RouteNotApprovedError(
                f"route {route_id} with status {route.status.value} is not allowed in {mode}"
            )
        return route
