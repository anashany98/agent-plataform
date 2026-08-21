"""Quality gates D-030: gates acordados, verdes sin ocultar deuda.

Puertas que ejecuta (todas fallan el proceso si no se cumplen):

- ``ruff-hard``: reglas ``E9,F`` (errores de sintaxis graves y pyflakes:
  imports sin usar, nombres indefinidos) sobre TODO el código propio:
  ``bridge-api/app``, ``tests``, ``bridge-api/tests`` y ``scripts``. Debe
  ser 0. El orden de imports (I001) es deuda estética y se controla por el
  trinquete, no por este gate de corrección.
- ``ruff-clean-zone``: reglas completas del proyecto sobre la zona limpia
  (módulos nuevos y tests). Debe ser 0.
- ``ruff-ratchet``: reglas completas sobre la zona legacy con trinquete:
  la deuda no puede superar el baseline de ``scripts/quality_baseline.json``.
  Reducirla exige actualizar el baseline (``--update-baseline``), de modo
  que la deuda permanece visible y nunca crece en silencio.
- ``llm-judge`` (opt-in, ``--with-judge``): gate de regresión de
  naturalidad del chat. Se ejecuta SOLO cuando cambian los archivos de
  prompt/chat (``--force-judge`` fuerza la ejecución) y FALLA el pipeline
  si la media global del evaluador LLM-as-judge baja del umbral
  (``--judge-threshold``, 4.0 por defecto) sobre la evidencia de validación
  en vivo más reciente. Sin evidencia o sin juez de referencia alcanzable
  hace SKIP (fail-open auditado: la infraestructura ausente nunca tumba el
  pipeline). Juez de referencia: qwen3-14b en LM Studio local (T-039);
  ``--judge-spec``/``--judge-base-url``/``QUALITY_GATE_JUDGE_SPEC`` lo
  cambian.

Opcional: ``--with-tests`` ejecuta el corpus pytest combinado y
``--with-portal`` el typecheck/test del portal. Por defecto solo corre
ruff para mantener el gate rápido y hermético.

La configuración de reglas vive en ``bridge-api/pyproject.toml``
(``E,F,I,B,UP`` sin ``E501``/``B008``; B008 excluido por el patrón
estándar ``Depends(...)`` de FastAPI, consenso del bloque P1).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = DEFAULT_ROOT / "scripts" / "quality_baseline.json"

CLEAN_ZONE_FILES = (
    "bridge-api/app/services/rag_security.py",
    "bridge-api/app/services/observability.py",
    "bridge-api/app/services/lifecycle.py",
    "bridge-api/app/services/automations.py",
    "bridge-api/app/services/agent_ai.py",
    "bridge-api/app/services/backup.py",
    "bridge-api/app/services/catalog_provider.py",
    "bridge-api/app/services/crm_provider.py",
    "bridge-api/app/services/redis_backend.py",
    "bridge-api/app/services/outbox_worker.py",
    "scripts/audit_dependencies.py",
    "scripts/quality_gates.py",
)

# Archivos de prompt/chat cuya modificación dispara el gate de regresión
# LLM-as-judge. ``git status --porcelain`` los detecta (modificados O
# nuevos/untracked, p. ej. los scripts de validación aún sin commitear).
CHAT_JUDGE_FILES = (
    "bridge-api/app/services/agent_ai.py",
    "bridge-api/app/main.py",
    "scripts/validate_chat_live.py",
    "scripts/llm_judge_naturalness.py",
    "tests/regression/test_p1_agent_ai.py",
)

# Juez de referencia del gate: qwen3-14b en LM Studio local, recomendado en
# T-039 por notas más consistentes y justificadas que deepseek-r1:8b (cuya
# severidad deja el baseline por debajo del umbral por diseño).
JUDGE_REFERENCE_SPEC = "openai_compatible:qwen3-14b"
JUDGE_REFERENCE_BASE_URL = "http://127.0.0.1:1234/v1"
JUDGE_THRESHOLD = 4.0
JUDGE_RUNS = 1  # el gate prioriza velocidad; ``--judge-runs`` sube consistencia
CLEAN_ZONE_DIRS = ("tests", "bridge-api/tests")

LEGACY_ZONE = "bridge-api/app"
HARD_ZONE = ("bridge-api/app", "tests", "bridge-api/tests", "scripts")


@dataclass(slots=True)
class GateResult:
    name: str
    passed: bool
    issues: int
    detail: str


def _run_ruff(root: Path, args: list[str], concise: bool = False) -> tuple[int, str]:
    # Targets such as tests/** live outside bridge-api/, so Ruff would otherwise
    # discover a different configuration (or its defaults) depending on cwd.
    config = root / "bridge-api" / "pyproject.toml"
    cmd = [sys.executable, "-m", "ruff", "check", "--config", str(config), *args]
    if concise:
        cmd.insert(4, "--output-format")
        cmd.insert(5, "concise")
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    _rc = proc.returncode
    return _rc, (proc.stdout or "") + (proc.stderr or "")


def _count_issues(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("Found ") and " error" in line:
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                continue
    return 0


def _count_issues_by_rule(output: str) -> dict[str, int]:
    """Desglose por regla del output de ruff (``path:line:col: CODE msg``)."""

    by_rule: dict[str, int] = {}
    for line in output.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        tokens = parts[3].strip().split()
        if not tokens:
            continue
        code = tokens[0]
        if not code.isalnum():
            continue
        by_rule[code] = by_rule.get(code, 0) + 1
    return by_rule


def gate_ruff_hard(root: Path) -> GateResult:
    rc, output = _run_ruff(root, ["--select", "E9,F", *HARD_ZONE])
    issues = _count_issues(output)
    return GateResult(
        name="ruff-hard",
        passed=rc == 0,
        issues=issues,
        detail="E9,F sobre todo el código propio" + ("" if rc == 0 else f"\n{output}"),
    )


def gate_ruff_clean_zone(root: Path) -> GateResult:
    targets: list[str] = []
    for rel in CLEAN_ZONE_FILES:
        if (root / rel).exists():
            targets.append(rel)
    for rel in CLEAN_ZONE_DIRS:
        if (root / rel).exists():
            targets.append(rel)
    if not targets:
        return GateResult("ruff-clean-zone", True, 0, "sin objetivos presentes")
    rc, output = _run_ruff(root, targets)
    issues = _count_issues(output)
    return GateResult(
        name="ruff-clean-zone",
        passed=rc == 0,
        issues=issues,
        detail="reglas completas sobre la zona limpia" + ("" if rc == 0 else f"\n{output}"),
    )


def _legacy_targets(root: Path) -> list[str]:
    clean_files = {(root / rel).resolve() for rel in CLEAN_ZONE_FILES}
    targets: list[str] = []
    app_root = root / LEGACY_ZONE
    for path in sorted(app_root.rglob("*.py")):
        if path.resolve() in clean_files:
            continue
        targets.append(str(path.relative_to(root)))
    return targets


def gate_ruff_ratchet(root: Path, baseline: int) -> GateResult:
    targets = _legacy_targets(root)
    if not targets:
        return GateResult("ruff-ratchet", True, 0, "sin zona legacy presente")
    rc, output = _run_ruff(root, targets)
    issues = _count_issues(output)
    passed = issues <= baseline
    detail = f"deuda legacy {issues} (baseline {baseline})"
    if not passed:
        detail += "\nLa deuda legacy supera el baseline: corrija los nuevos hallazgos."
    elif issues < baseline:
        detail += "\nLa deuda se redujo: ejecute --update-baseline para fijar el nuevo piso."
    return GateResult(name="ruff-ratchet", passed=passed, issues=issues, detail=detail)


def gate_pytest(root: Path) -> GateResult:
    env_python = sys.executable
    for order in (("tests", "bridge-api/tests"), ("bridge-api/tests", "tests")):
        cmd = [env_python, "-m", "pytest", "-q", *order]
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "PYTHONPATH": str(root / "bridge-api")},
        )
        if proc.returncode != 0:
            # Visibilidad de fallos en CI: listar TODOS los tests caídos,
            # no solo las últimas líneas (el corpus puede fallar en varios
            # puntos y el resumen recortado oculta la causa).
            output_lines = (proc.stdout or "").splitlines()
            failed_lines = [line for line in output_lines if line.startswith("FAILED")]
            tail = "\n".join(output_lines[-5:])
            detail = "\n".join(part for part in ("\n".join(failed_lines), tail) if part)
            return GateResult("pytest", False, 1, f"corpus {' '.join(order)} falló\n{detail}")
    return GateResult("pytest", True, 0, "corpus combinado verde en ambos órdenes")


def gate_portal(root: Path) -> GateResult:
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    for script in ("typecheck", "test"):
        proc = subprocess.run(
            [npm, "run", script],
            cwd=str(root / "portal"),
            capture_output=True,
            text=True,
            timeout=600,
            shell=sys.platform.startswith("win"),
        )
        if proc.returncode != 0:
            tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-8:])
            return GateResult("portal", False, 1, f"npm run {script} falló\n{tail}")
    return GateResult("portal", True, 0, "typecheck y tests del portal verdes")


def load_baseline() -> int:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return int(payload["legacy_zone_ruff_full"])


def update_baseline(root: Path, issues: int) -> None:
    baseline_path = root / "scripts" / "quality_baseline.json"
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    payload["legacy_zone_ruff_full"] = issues
    # El desglose por regla debe cuadrar con el total: se recalcula con la
    # misma selección de la zona legacy que usa el trinquete (formato
    # concise: una línea por diagnóstico ``path:line:col: CODE msg``).
    _, output = _run_ruff(root, _legacy_targets(root), concise=True)
    by_rule = dict(sorted(_count_issues_by_rule(output).items(), key=lambda kv: -kv[1]))
    if sum(by_rule.values()) == issues:
        payload["by_rule"] = by_rule
    baseline_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _git_files_changed(root: Path, files: tuple[str, ...]) -> bool | None:
    """True si algún archivo cambió o es nuevo vs git; False si ninguno;
    None si no se puede determinar (sin git) — en ese caso el gate corre."""

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", *files],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool((proc.stdout or "").strip())


def _load_judge(root: Path):
    """Importa el evaluador LLM-as-judge (con bridge-api en el path para
    ``app.config``), aislado para que los tests lo sustituyan."""

    sys.path.insert(0, str(root / "scripts"))
    sys.path.insert(0, str(root / "bridge-api"))
    import llm_judge_naturalness  # noqa: PLC0415

    return llm_judge_naturalness


def _judge_reachable(cfg: dict, timeout: float = 3.0) -> bool:
    """Probe barato de disponibilidad del juez (fail-open si falla).

    Para ``anthropic`` no hay probe local barato: se asume alcanzable y el
    propio evaluador devuelve records sin puntuar si el servidor falla (el
    gate hace SKIP entonces)."""

    provider = cfg.get("provider") or ""
    base = (cfg.get("base_url") or "").strip()
    if provider == "openai_compatible":
        url = base.rstrip("/") + "/models"
    elif provider == "ollama":
        url = base.replace("/api/generate", "").rstrip("/") + "/api/tags"
    else:
        return True
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - probe best-effort
        return False


def _write_gate_evidence(root: Path, cfg: dict, records: list[dict], agg: dict, threshold: float, passed: bool) -> None:
    """Registra el resultado del gate como artefacto auditable en
    ``logs/rehearsal/`` (misma ubicación que la evidencia del evaluador)."""

    out_dir = root / "logs" / "rehearsal"
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_file = out_dir / f"quality_gate_judge_{started}.json"
    out_file.write_text(
        json.dumps(
            {
                "generated_at": started,
                "gate": "llm-judge",
                "judge": {"provider": cfg.get("provider"), "model": cfg.get("model")},
                "threshold": threshold,
                "aggregate": agg,
                "verdict": "PASS" if passed else "FAIL",
                "records": len(records),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def gate_llm_judge(
    root: Path,
    *,
    changed: bool | None = None,
    judge_spec: str = "",
    judge_base_url: str = "",
    threshold: float = JUDGE_THRESHOLD,
    force: bool = False,
    runs: int = JUDGE_RUNS,
) -> GateResult:
    """Gate de regresión de naturalidad del chat (LLM-as-judge).

    - Sin ``force`` y sin cambios detectados en los archivos de prompt/chat
      → SKIP (gate rápido en cambios que no tocan el chat).
    - Sin evidencia de validación en vivo o sin juez alcanzable → SKIP
      (degradación fail-open auditada; nunca tumba el pipeline por
      infraestructura ausente).
    - Con evidencia y juez: ejecuta el evaluador sobre la validación en vivo
      más reciente y FALLA si la media global baja de ``threshold`` (4.0).
    """

    if not force:
        if changed is None:
            changed = _git_files_changed(root, CHAT_JUDGE_FILES)
        if changed is False:
            return GateResult("llm-judge", True, 0, "SKIP: sin cambios en prompt/chat")

    judge = _load_judge(root)
    evidence = sorted(judge.OUT_DIR.glob("chat_live_validation_*.json"))
    if not evidence:
        return GateResult(
            "llm-judge", True, 0, f"SKIP: sin evidencia de validación en {judge.OUT_DIR}"
        )

    spec = (
        judge_spec
        or os.getenv("QUALITY_GATE_JUDGE_SPEC", "").strip()
        or JUDGE_REFERENCE_SPEC
    )
    base_url = (
        judge_base_url
        or os.getenv("QUALITY_GATE_JUDGE_BASE_URL", "").strip()
        or JUDGE_REFERENCE_BASE_URL
    )
    cfg = judge.resolve_provider(spec, base_url, "")
    if not _judge_reachable(cfg):
        return GateResult(
            "llm-judge",
            True,
            0,
            f"SKIP: juez {cfg.get('provider')}/{cfg.get('model')} no alcanzable "
            f"({cfg.get('base_url')})",
        )

    records, persona = judge.load_records([evidence[-1]])
    if not records:
        return GateResult("llm-judge", True, 0, "SKIP: sin respuestas evaluables")
    history = judge.build_history(records)
    scored = judge._run_scores(records, history, persona, runs=runs, cfg=cfg)
    agg = judge.aggregate(scored, {})
    overall = agg.get("overall")
    if overall is None:
        return GateResult(
            "llm-judge",
            True,
            0,
            "SKIP: el juez no produjo puntuaciones válidas (¿servidor caído?)",
        )
    passed = overall >= threshold
    detail = (
        f"media global {overall} (umbral {threshold}) | "
        f"por dimensión {agg.get('by_dimension')} | "
        f"mínimos {agg.get('min_per_dimension')} | "
        f"juez {cfg.get('provider')}/{cfg.get('model')} | "
        f"{len(records)} respuestas | evidencia {evidence[-1].name}"
    )
    _write_gate_evidence(root, cfg, records, agg, threshold, passed)
    return GateResult("llm-judge", passed, 0 if passed else 1, detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quality gates D-030")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Raíz del repositorio")
    parser.add_argument("--baseline", type=int, default=None, help="Baseline manual (tests)")
    parser.add_argument("--with-tests", action="store_true", help="Ejecutar el corpus pytest")
    parser.add_argument("--with-portal", action="store_true", help="Ejecutar typecheck/test del portal")
    parser.add_argument(
        "--with-judge",
        action="store_true",
        help="Ejecutar el gate de regresión LLM-as-judge del chat (media global < umbral falla)",
    )
    parser.add_argument(
        "--force-judge",
        action="store_true",
        help="Ejecutar el gate del juez aunque no haya cambios en prompt/chat",
    )
    parser.add_argument("--judge-spec", default="", help="Especificación proveedor:modelo del juez (default: qwen3-14b/LM Studio)")
    parser.add_argument("--judge-base-url", default="", help="Base URL del juez (default: LM Studio local)")
    parser.add_argument("--judge-threshold", type=float, default=JUDGE_THRESHOLD, help="Umbral de media global (default: 4.0)")
    parser.add_argument("--judge-runs", type=int, default=JUDGE_RUNS, help="Pasadas del juez por respuesta (default: 1)")
    parser.add_argument("--update-baseline", action="store_true", help="Fijar el baseline a la deuda actual")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    baseline = args.baseline if args.baseline is not None else load_baseline()

    results = [
        gate_ruff_hard(root),
        gate_ruff_clean_zone(root),
        gate_ruff_ratchet(root, baseline),
    ]
    if args.with_tests:
        results.append(gate_pytest(root))
    if args.with_portal:
        results.append(gate_portal(root))
    if args.with_judge:
        results.append(
            gate_llm_judge(
                root,
                judge_spec=args.judge_spec,
                judge_base_url=args.judge_base_url,
                threshold=args.judge_threshold,
                force=args.force_judge,
                runs=args.judge_runs,
            )
        )

    failed = False
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[GATE] {result.name}: {status} ({result.issues} issues) — {result.detail.splitlines()[0]}")
        if not result.passed:
            failed = True
            for line in result.detail.splitlines()[1:]:
                print(f"       {line}")

    if args.update_baseline:
        legacy = gate_ruff_ratchet(root, 10**9)
        update_baseline(root, legacy.issues)
        print(f"[BASELINE] actualizado a {legacy.issues}")

    if failed:
        print("\nQuality gates D-030: FALLOS")
        return 1
    print("\nQuality gates D-030: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
