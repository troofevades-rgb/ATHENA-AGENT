"""Non-REPL ocode subcommands (import-from-hermes, etc.).

``ocode.__main__`` dispatches to handlers in this package when ``argv[1]``
matches a registered subcommand name; everything else falls through to the
interactive REPL.
"""
