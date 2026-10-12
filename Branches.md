# Branches — nettoyage

Branches fermées par archivage (tag `archive/<nom>` puis suppression). Le SHA reste accessible par le tag.

## Campagne E2 (groupe A) — étapes d'investigation

Référence courante : `E2_BASELINES.md` sur `main`. Baseline v1 `SUPERSEDED_UNRECOVERABLE`, v2 référence courante.

| Branche | SHA | Raison |
|---|---|---|
| `baseline/e2-reconstructed-2026-10-09` | 15ea667 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `debug/e2-pres8-baseline` | dccef80 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `debug/e2-pres8-trigger` | 9f3a535 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `diagnostic/e2-adversarial-depth-2026-10-09` | 1f0303a | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09` | a06aa7c | Fix nonce et exceptions non appliqué : voir issue à ouvrir (exception) |
| `diagnostic/e2-depth3-key-diff-2026-10-09` | 62bdec7 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `diagnostic/e2-depth3-nonce-adapter-2026-10-09` | 62bdec7 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `diagnostic/e2-honest-depth-pr15-2026-10-09` | 0f9dad3 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `diagnostic/e2-rlock-effect-2026-10-09` | a3d466e | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `docs/d5-e2-baselines-v6-8` | a0c99d1 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `docs/harmonize-s1-s6-status-2026-10-09` | aab204a | Remplacé par STATUS.md sur main (groupe D) |
| `forensic/e2-key-audit-20261009` | cf1b1ea | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `forensics/e2-i1-min-depth` | 938aac5 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `forensics/e2-provenance-sha256-20261009` | 9ee3b77 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `repro/e1-e2-20261009` | f37eef4 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `test/e2-differential-pre-s8` | 87949cd | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |
| `test/e2-strict-harness-20261009` | 3d84f85 | Étape d'investigation E2 (groupe A), conservée par tag ; non relue individuellement |

## Exceptions

- `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09` — SHA pinné `a06aa7c`. 28 commits, non appliqués sur main : l'explorateur de main n'a pas la fonction `nonce_for`. À tracker : décider si les comptes v2 doivent être régénérés après application.
