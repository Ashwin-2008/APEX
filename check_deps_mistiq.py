import importlib

for name in ("sklearn", "numpy", "sqlalchemy", "fastapi", "pytest", "pydantic"):
    try:
        mod = importlib.import_module(name)
        print(name, getattr(mod, "__version__", "ok"))
    except Exception as exc:  # pragma: no cover
        print(name, "MISSING", exc)
