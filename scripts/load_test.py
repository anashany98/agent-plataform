#!/usr/bin/env python3
"""Prueba de carga acotada contra una instalación del bridge (SS-06).

Genera tráfico de lectura determinista durante un tiempo limitado y emite
un informe de latencias (p50/p95/p99/máx), tasa y errores por endpoint.
Es la herramienta de evidencia del stop-ship SS-06: los límites medidos
(requisito de capacidad) salen de aquí, no de estimaciones.

Uso típico:

    python scripts/load_test.py --base-url http://localhost:9000 \
        --duration-sec 60 --concurrency 5 --token <JWT> \
        --output logs/load_report.json

Solo lectura: nunca muta datos. El token es opcional; sin él el escenario
se limita a endpoints públicos (/live, /health). Con él añade el listado
paginado de catálogo (la ruta pesada real con 41k SKUs). Falla (exit 1)
si la tasa de error supera ``--max-error-pct`` o si el prefight inicial
no consigue alcanzar la instancia.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "http://localhost:9000"
CATALOG_PATH = "/catalog/products"


@dataclass
class Sample:
    endpoint: str
    status: int | None
    latency_ms: float
    error: str | None = None


@dataclass
class Aggregates:
    count: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)

    def add(self, sample: Sample) -> None:
        self.count += 1
        if sample.error is not None or sample.status is None or sample.status >= 400:
            self.errors += 1
        self.latencies.append(sample.latency_ms)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(round((pct / 100) * (len(sorted_values) - 1))))
    return sorted_values[index]


def _summarize(name: str, samples: list[Sample]) -> dict[str, object]:
    agg = Aggregates()
    for sample in samples:
        agg.add(sample)
    ordered = sorted(agg.latencies)
    return {
        "endpoint": name,
        "requests": agg.count,
        "errors": agg.errors,
        "error_pct": round(100 * agg.errors / agg.count, 2) if agg.count else 0.0,
        "latency_ms_p50": round(_percentile(ordered, 50), 1),
        "latency_ms_p95": round(_percentile(ordered, 95), 1),
        "latency_ms_p99": round(_percentile(ordered, 99), 1),
        "latency_ms_max": round(max(ordered), 1) if ordered else 0.0,
    }


def build_scenario(client: httpx.Client, base_url: str, token: str | None) -> list[dict[str, object]]:
    """Escenario ponderado: (peso, método, ruta, headers)."""

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    scenario: list[dict[str, object]] = [
        {"weight": 2, "method": "GET", "path": "/live", "headers": {}},
        {"weight": 2, "method": "GET", "path": "/health", "headers": {}},
    ]
    if token:
        # Ruta pesada real: paginación sobre el catálogo completo.
        probe = client.get(f"{base_url}{CATALOG_PATH}?limit=5", headers=headers)
        if probe.status_code < 400:
            scenario.append(
                {
                    "weight": 6,
                    "method": "GET",
                    "path": f"{CATALOG_PATH}?limit=50&offset=0",
                    "headers": headers,
                }
            )
        else:
            print(
                f"[load] Aviso: {CATALOG_PATH} respondió {probe.status_code}; "
                "el escenario se limita a endpoints públicos."
            )
    return scenario


def _pick(scenario: list[dict[str, object]], weights: list[int], total: int) -> dict[str, object]:
    rng = _random_for_thread()
    target = rng.randrange(total) if total > 0 else 0
    cumulative = 0
    for entry, weight in zip(scenario, weights, strict=True):
        cumulative += weight
        if target < cumulative:
            return entry
    return scenario[-1]


_RNG_LOCK = threading.Lock()


def _random_for_thread():
    import random

    return random.Random(threading.get_ident() ^ time.monotonic_ns())


def main(argv: list[str] | None = None) -> int:
    # Consolas Windows (cp1252) no saben imprimir símbolos como «≤» del
    # informe: forzamos UTF-8 con sustitución para que el resultado nunca
    # dependa de la codepage del terminal.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--duration-sec", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--ramp-sec", type=float, default=0.0)
    parser.add_argument("--token", default="")
    parser.add_argument("--max-error-pct", type=float, default=1.0)
    parser.add_argument("--timeout-sec", type=float, default=10.0)
    parser.add_argument("--output", default="", help="Ruta opcional del informe JSON")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    samples: list[Sample] = []
    lock = threading.Lock()
    stop_at = time.monotonic() + args.duration_sec

    # Preflight: fallar rápido con mensaje claro si no se alcanza la instancia.
    try:
        probe = httpx.get(f"{base_url}/live", timeout=args.timeout_sec)
        probe.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - mensaje operativo claro
        print(f"[load] Preflight falló contra {base_url}/live: {exc}", file=sys.stderr)
        return 2

    with httpx.Client(timeout=args.timeout_sec) as client:
        scenario = build_scenario(client, base_url, args.token.strip())
        weights = [int(entry["weight"]) for entry in scenario]
        total_weight = sum(weights)

        def worker(worker_index: int) -> None:
            if args.ramp_sec > 0:
                time.sleep(args.ramp_sec * worker_index / max(1, args.concurrency - 1))
            local_client = httpx.Client(timeout=args.timeout_sec)
            try:
                while time.monotonic() < stop_at:
                    entry = _pick(scenario, weights, total_weight)
                    started = time.perf_counter()
                    status: int | None = None
                    error: str | None = None
                    try:
                        response = local_client.request(
                            str(entry["method"]),
                            f"{base_url}{entry['path']}",
                            headers=dict(entry["headers"]),
                        )
                        status = response.status_code
                    except Exception as exc:  # noqa: BLE001 - se registra y sigue
                        error = type(exc).__name__
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    with lock:
                        samples.append(
                            Sample(str(entry["path"]), status, elapsed_ms, error)
                        )
            finally:
                local_client.close()

        threads = [
            threading.Thread(target=worker, args=(index,), daemon=True)
            for index in range(max(1, args.concurrency))
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    by_endpoint: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_endpoint[sample.endpoint].append(sample)

    duration_actual = max(0.001, args.duration_sec)
    report: dict[str, object] = {
        "base_url": base_url,
        "duration_sec": args.duration_sec,
        "concurrency": args.concurrency,
        "total_requests": len(samples),
        "throughput_rps": round(len(samples) / duration_actual, 2),
        "endpoints": [
            _summarize(endpoint, endpoint_samples)
            for endpoint, endpoint_samples in sorted(by_endpoint.items())
        ],
    }
    total_summary = _summarize("TOTAL", samples)
    report["total"] = total_summary
    report["error_pct"] = total_summary["error_pct"]

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)

    error_pct = float(total_summary["error_pct"])
    if error_pct > args.max_error_pct:
        print(
            f"[load] FALLÓ: tasa de error {error_pct}% supera el umbral {args.max_error_pct}%",
            file=sys.stderr,
        )
        return 1
    print(
        f"[load] OK: {len(samples)} peticiones, {report['throughput_rps']} req/s, "
        f"errores {error_pct}% ≤ umbral {args.max_error_pct}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
