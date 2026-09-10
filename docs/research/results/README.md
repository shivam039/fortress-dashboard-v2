# Research results directory

This directory is where a real FORTRESS-R2 forward-return validation result
belongs once one exists: `r2_validation_report.json`, produced by

```bash
PYTHONPATH=.:engine .venv/bin/python -m research.forward_return_validation \
  /path/to/real-r1-dataset.sqlite \
  --benchmark NIFTY \
  --json docs/research/results/r2_validation_report.json
```

`engine/utils/research_evidence.py` (FORTRESS-V2) reads exactly this path by
default — override it with `FORTRESS_RESEARCH_RESULTS_DIR` if a deployment
needs a different location. Until that file exists, `GET
/api/research-evidence` honestly reports `available: false` for every score;
see `docs/research/REAL_VALIDATION_RESULTS.md` for why no real result exists
in this repository yet.

Only the validation *report* JSON belongs here, not the R1 SQLite dataset or
its immutable input bundle — those can be large and are reproducible from
documented commands, so keep them alongside the archive that owns them
instead of committing them to this repository.
