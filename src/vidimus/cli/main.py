"""Vidimus CLI entry point.

Commands:
  vidimus init                                 Initialize a workspace + keys
  vidimus keys generate                        Generate a new Ed25519 keypair
  vidimus keys list                            List local keys
  vidimus attest --since 24h --output r.json   Generate a signed attestation
  vidimus verify r.json                        Verify offline
  vidimus version                              Print version
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vidimus import __version__
from vidimus.audit.attest import attest as do_attest
from vidimus.audit.attest import verify as do_verify
from vidimus.audit.keys import generate_keypair, load_keypair, save_keypair
from vidimus.audit.schemas import Attestation
from vidimus.config import get_config, init as init_config

console = Console()


@click.group()
@click.version_option(__version__, prog_name="vidimus")
def cli() -> None:
    """Vidimus — the trust layer for agentic AI."""


@cli.command()
@click.option("--workspace", default="default", help="Workspace name.")
def init(workspace: str) -> None:
    """Initialize Vidimus configuration and generate a keypair."""
    config = init_config(workspace=workspace)
    keys_dir = config.home_dir / "keys"
    keys_dir.mkdir(parents=True, exist_ok=True)

    # Generate first key if none exists.
    existing = list(keys_dir.glob("*.priv.pem"))
    if not existing:
        kp = generate_keypair()
        priv, pub = save_keypair(kp, keys_dir)
        console.print(
            f"[green]✓[/green] Initialized workspace '[bold]{workspace}[/bold]'"
        )
        console.print(f"  home dir : {config.home_dir}")
        console.print(f"  key      : {kp.fingerprint[:16]}…")
        console.print(f"  private  : {priv} (0600)")
        console.print(f"  public   : {pub}")
    else:
        console.print(
            f"[yellow]i[/yellow] Workspace '[bold]{workspace}[/bold]' already initialized "
            f"({len(existing)} key(s) present)"
        )


@cli.group()
def keys() -> None:
    """Manage Ed25519 keys."""


@keys.command(name="generate")
def keys_generate() -> None:
    """Generate a new Ed25519 keypair and add it to the local keystore."""
    config = get_config()
    keys_dir = config.home_dir / "keys"
    kp = generate_keypair()
    priv, pub = save_keypair(kp, keys_dir)
    console.print(f"[green]✓[/green] new key: {kp.fingerprint}")
    console.print(f"  private: {priv}")
    console.print(f"  public : {pub}")


@keys.command(name="list")
def keys_list() -> None:
    """List local key fingerprints."""
    config = get_config()
    keys_dir = config.home_dir / "keys"
    if not keys_dir.exists():
        console.print("[yellow]no keys yet — run `vidimus init` first[/yellow]")
        return

    privs = sorted(keys_dir.glob("*.priv.pem"))
    if not privs:
        console.print("[yellow]no keys yet — run `vidimus init` first[/yellow]")
        return

    table = Table(title="Local keys")
    table.add_column("Fingerprint", style="bold")
    table.add_column("File")
    for p in privs:
        fp = p.name.replace(".priv.pem", "")
        table.add_row(fp[:32] + "…", str(p))
    console.print(table)


@cli.command()
@click.option(
    "--since",
    default="24h",
    help="Time window from now backwards (e.g. 24h, 7d, 30m).",
)
@click.option(
    "--metric",
    "metrics",
    multiple=True,
    default=("hallucination",),
    help="Metric name (repeatable).",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=Path("attestation.json"),
    help="Output file path.",
)
@click.option(
    "--key",
    "key_fingerprint",
    default=None,
    help="Fingerprint of the key to sign with. Defaults to the first available key.",
)
@click.option(
    "--judges",
    default="stub:judge-1,stub:judge-2,stub:judge-3",
    help="Comma-separated judge identifiers.",
)
@click.option(
    "--seed",
    type=int,
    default=None,
    help="Optional RNG seed for reproducible bootstrap CIs.",
)
def attest(
    since: str,
    metrics: tuple[str, ...],
    output: Path,
    key_fingerprint: str | None,
    judges: str,
    seed: int | None,
) -> None:
    """Generate a signed attestation over recent traces."""
    config = get_config()
    keys_dir = config.home_dir / "keys"

    # Locate signing key.
    if key_fingerprint:
        priv_path = keys_dir / f"{key_fingerprint}.priv.pem"
        if not priv_path.exists():
            console.print(f"[red]✗[/red] key {key_fingerprint} not found in {keys_dir}")
            sys.exit(2)
    else:
        candidates = sorted(keys_dir.glob("*.priv.pem"))
        if not candidates:
            console.print("[red]✗[/red] no keys found. run `vidimus init` first.")
            sys.exit(2)
        priv_path = candidates[0]

    kp = load_keypair(priv_path)

    # Parse time window.
    delta = _parse_duration(since)
    end = datetime.now(timezone.utc)
    start = end - delta

    judge_list = [j.strip() for j in judges.split(",") if j.strip()]

    try:
        attestation = do_attest(
            metrics=list(metrics),
            period_start=start,
            period_end=end,
            keypair=kp,
            judges=judge_list,
            seed=seed,
        )
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        sys.exit(1)

    output.write_text(attestation.model_dump_json(indent=2))
    console.print(f"[green]✓[/green] attestation written to [bold]{output}[/bold]")
    console.print(f"  workspace    : {attestation.workspace}")
    console.print(f"  trace count  : {attestation.trace_count}")
    console.print(f"  Merkle root  : {attestation.merkle_root[:32]}…")
    console.print(f"  issuer fp    : {attestation.issuer_pubkey_fingerprint[:32]}…")
    for m in attestation.metrics:
        agreement = (
            f"κ={m.judge_agreement:.2f}" if m.judge_agreement is not None else "n/a"
        )
        console.print(
            f"  {m.name:24} {m.point_estimate:6.2%} "
            f"[CI {m.ci_low:.2%} – {m.ci_high:.2%}] "
            f"n={m.n}  {agreement}"
        )


@cli.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def verify(file: Path) -> None:
    """Verify an attestation file offline."""
    data = json.loads(file.read_text())
    attestation = Attestation.model_validate(data)
    ok, issues, warnings = do_verify(attestation)

    if ok:
        console.print(f"[green]✓[/green] attestation [bold]{file.name}[/bold] is valid")
        if warnings:
            console.print("[yellow]⚠[/yellow]  warnings:")
            for w in warnings:
                console.print(f"    - {w}")
    else:
        console.print(f"[red]✗[/red] attestation [bold]{file.name}[/bold] has fatal issues:")
        for issue in issues:
            console.print(f"    - {issue}")
        if warnings:
            console.print("[yellow]⚠[/yellow]  additional warnings:")
            for w in warnings:
                console.print(f"    - {w}")
        sys.exit(1)

    console.print(f"  workspace    : {attestation.workspace}")
    console.print(f"  period       : {attestation.period_start} → {attestation.period_end}")
    console.print(f"  trace count  : {attestation.trace_count}")
    console.print(f"  Merkle root  : {attestation.merkle_root}")
    console.print(f"  signed by    : {attestation.issuer_pubkey_fingerprint}")
    for m in attestation.metrics:
        agreement = (
            f"κ={m.judge_agreement:.2f}" if m.judge_agreement is not None else "n/a"
        )
        console.print(
            f"  {m.name:24} {m.point_estimate:6.2%} "
            f"[CI {m.ci_low:.2%} – {m.ci_high:.2%}] "
            f"n={m.n}  {agreement}"
        )


@cli.command()
def version() -> None:
    """Print the Vidimus version."""
    console.print(f"vidimus {__version__}")


_DURATION_RE = re.compile(r"^(?P<num>\d+)\s*(?P<unit>[smhd])$")


def _parse_duration(s: str) -> timedelta:
    m = _DURATION_RE.match(s.strip())
    if not m:
        raise click.BadParameter(f"cannot parse duration '{s}', expected like '24h' or '7d'")
    n = int(m.group("num"))
    unit = m.group("unit")
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


if __name__ == "__main__":
    cli()
