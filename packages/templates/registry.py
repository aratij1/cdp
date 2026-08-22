"""Loads `Template` definitions from `config/templates/*.yaml` and serves
lookups by (form_type, version) or template_id. Adding a new payer form
variant is a new YAML file, not a code change (see
docs/CONFIGURATION_GUIDE.md)."""

from __future__ import annotations

from pathlib import Path

import yaml
from PIL import Image

from packages.domain.enums import ClaimFormType
from packages.templates.canonical import load_canonical_image
from packages.templates.models import Template

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "templates"
DEFAULT_CANONICAL_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


class TemplateNotFoundError(KeyError):
    pass


class TemplateRegistry:
    def __init__(
        self,
        templates: list[Template] | None = None,
        canonical_dir: Path | None = None,
    ) -> None:
        self._by_id_version: dict[tuple[str, str], Template] = {}
        self._by_form_type: dict[ClaimFormType, list[Template]] = {}
        self._template_dirs: dict[tuple[str, str], Path] = {}
        self._canonical_dir = canonical_dir
        for template in templates or []:
            self.register(template)

    def register(self, template: Template, source_dir: Path | None = None) -> None:
        self._by_id_version[(template.template_id, template.version)] = template
        self._by_form_type.setdefault(template.form_type, []).append(template)
        if source_dir is not None:
            self._template_dirs[(template.template_id, template.version)] = source_dir

    def load_reference_image(self, template: Template) -> Image.Image | None:
        """Loads the operator-supplied reference scan configured via
        `Template.reference_image_path`, resolved relative to the directory
        the template's YAML was loaded from. Returns `None` (never raises)
        when unset or the file doesn't exist, so callers can always treat
        real geometric alignment as an optional enhancement -- see
        docs/ARCHITECTURE.md and `Template.reference_image_path`."""
        if template.reference_image_path is None:
            if self._canonical_dir is None:
                return None
            package_dir = self._canonical_dir / template.template_id
            if not package_dir.is_dir():
                return None
            return load_canonical_image(package_dir, template)
        source_dir = self._template_dirs.get((template.template_id, template.version))
        if source_dir is None:
            return None
        path = source_dir / template.reference_image_path
        if not path.is_file():
            return None
        image = Image.open(path)
        image.load()
        return image.convert("L")

    def get(self, template_id: str, version: str) -> Template:
        try:
            return self._by_id_version[(template_id, version)]
        except KeyError as exc:
            raise TemplateNotFoundError(f"{template_id}@{version}") from exc

    def latest_for_form_type(self, form_type: ClaimFormType) -> Template:
        """Highest `version` string, lexicographically -- versions in this
        registry follow YYYY.MM or similar sortable schemes; a numeric
        semver comparator can replace this if that stops being true."""
        candidates = self._by_form_type.get(form_type, [])
        if not candidates:
            raise TemplateNotFoundError(f"no templates registered for {form_type}")
        return max(candidates, key=lambda t: t.version)

    def all_for_form_type(self, form_type: ClaimFormType) -> list[Template]:
        return list(self._by_form_type.get(form_type, []))

    @classmethod
    def load_from_directory(
        cls,
        directory: Path = DEFAULT_TEMPLATE_DIR,
        canonical_dir: Path | None = DEFAULT_CANONICAL_DIR,
    ) -> TemplateRegistry:
        registry = cls(canonical_dir=canonical_dir)
        for path in sorted(directory.glob("*.yaml")):
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            registry.register(Template.model_validate(data), source_dir=path.parent)
        return registry
