"""Sammelimport aller Modelle.

Alembic und die Introspektionstests brauchen ein vollstaendiges Register. Neue
Module werden hier eingetragen — vergisst man das, schlaegt
``tests/test_mandantentrennung.py::test_alle_module_sind_registriert`` fehl.
"""

from __future__ import annotations

import belegwerk.check.modelle as check_modelle
import belegwerk.delta.modelle as delta_modelle
import belegwerk.kern.modelle as kern_modelle

__all__ = ["kern_modelle", "check_modelle", "delta_modelle"]
