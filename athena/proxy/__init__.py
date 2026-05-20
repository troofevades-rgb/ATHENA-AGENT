"""athena proxy — local OpenAI-compatible HTTP endpoint (T3-01).

Importing the submodules has no side effects; the ``athena proxy``
subcommand wires them together at runtime. FastAPI/uvicorn are
declared under the ``proxy`` optional-extra so headless installs
don't pull them in.
"""
