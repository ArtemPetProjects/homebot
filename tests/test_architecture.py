# PURPOSE: архитектурный страж: слой domain не зависит от сетевых/инфраструктурных библиотек.
import importlib
import pkgutil
import unittest

DOMAIN_PACKAGE = "homebot.domain"

# Импорты, которые недопустимы в доменном слое (он не должен знать о сети, Telegram, файловом вводе-выводе инфраструктуры).
FORBIDDEN_MODULES = (
    "requests",
    "urllib",
    "urllib.request",
    "urllib.error",
    "telegram",
    "socket",
    "subprocess",
)


def _iter_domain_modules():
    package = importlib.import_module(DOMAIN_PACKAGE)
    package_path = getattr(package, "__path__", [])
    for module_info in pkgutil.iter_modules(package_path):
        full_name = f"{DOMAIN_PACKAGE}.{module_info.name}"
        yield full_name


def _collect_forbidden_imports(module_name):
    module = importlib.import_module(module_name)
    source_file = getattr(module, "__file__", None)
    if not source_file:
        return []
    with open(source_file, "r", encoding="utf-8") as handle:
        source = handle.read()
    found = []
    for forbidden in FORBIDDEN_MODULES:
        # Ищем импорты вида: import forbidden, from forbidden import, import forbidden.sub
        for prefix in (f"import {forbidden}", f"from {forbidden}"):
            if prefix in source:
                found.append((forbidden, prefix))
    return found


class ArchitectureTest(unittest.TestCase):
    def test_domain_has_no_infrastructure_imports(self):
        problems = {}
        for module_name in _iter_domain_modules():
            found = _collect_forbidden_imports(module_name)
            if found:
                problems[module_name] = found
        self.assertFalse(
            problems,
            "Доменный слой не должен зависеть от инфраструктуры: "
            + "; ".join(f"{m}: {i}" for m, i in problems.items()),
        )


if __name__ == "__main__":
    unittest.main()
