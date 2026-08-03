"""Carregador transitório dos módulos funcionais do SGE.

Mantém compatibilidade total com os nomes de endpoints e com os auxiliares
históricos enquanto o monólito é separado progressivamente por domínio.
Cada ficheiro funcional é executado num namespace próprio e sincronizado com
o contexto da aplicação apenas durante o arranque.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, MutableMapping


_LOADED_FEATURES: list[ModuleType] = []


def _public_context(context: MutableMapping[str, Any]) -> dict[str, Any]:
    """Remove metadados internos que nunca devem ser copiados entre módulos."""
    return {name: value for name, value in context.items() if not name.startswith("__")}


def sync_feature_context(context: MutableMapping[str, Any]) -> None:
    """Sincroniza definições finais entre os módulos já carregados.

    Esta camada existe para preservar dependências históricas durante a
    migração. Novos módulos devem preferir serviços explícitos em vez deste
    contexto de compatibilidade.
    """
    shared = _public_context(context)
    for module in _LOADED_FEATURES:
        module.__dict__.update(shared)


def load_feature(name: str, context: MutableMapping[str, Any]) -> ModuleType:
    """Carrega um domínio do SGE e preserva os endpoints Flask existentes."""
    base_dir = Path(str(context["BASE_DIR"]))
    source_path = base_dir / "sge_modules" / f"{name}.py"
    if not source_path.is_file():
        raise RuntimeError(f"Módulo funcional do SGE não encontrado: {source_path}")

    module_name = f"sge_modules.{name}"
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível preparar o módulo: {name}")

    module = importlib.util.module_from_spec(spec)
    module.__dict__.update(_public_context(context))
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    _LOADED_FEATURES.append(module)
    context.update(_public_context(module.__dict__))
    sync_feature_context(context)
    return module


def loaded_feature_names() -> tuple[str, ...]:
    """Expõe a ordem de carga para diagnóstico e testes de arquitectura."""
    return tuple(module.__name__.rsplit(".", 1)[-1] for module in _LOADED_FEATURES)
