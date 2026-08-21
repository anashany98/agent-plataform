"""Routers de dominio del Bridge API (B-01).

``main.py`` actúa como ensamblador: cada dominio expone un ``APIRouter``
que se registra con ``include_router``. Los handlers se mueven tal cual,
sin cambiar comportamiento ni rutas.
"""
