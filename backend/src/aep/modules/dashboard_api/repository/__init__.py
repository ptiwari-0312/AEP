"""No repository layer here, deliberately: this module owns no database table of its own — it
composes other modules' public `services/`, never their `repository/` (docs/architecture/
02-repo-design.md §2). Every other module in this codebase has a real `repository/`; this one's
emptiness is the module's actual shape, not an unfinished part of it.
"""
