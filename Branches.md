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

## Lot 3 — groupes B et C

| Branche | SHA | Raison |
|---|---|---|
| `feature/g0-s11-transition-object` | 0b5af5f | Contenue dans main (aucun commit hors main) |
| `feat/g0-s6-reconciliation` | c56a1b0 | Remplacée par S6b et la passe 2 sur main ; retry_eligible retiré |
| `feature/g0-s7-ed25519` | d515c21 | Remplacée par les tests S7 de main ; attestations signées |
| `feature/g0-s8-concurrent-admission` | 8a32b87 | Remplacée par les tests S8 de main ; non relue individuellement |
| `feature/g0-s10-tau-scope-boundary` | 01efae1 | Remplacée par les tests S10 de main ; non relue individuellement |
| `feature/s12a-s12h-cross-realm-conformance` | c950c56 | Remplacée par S12 sur main ; artefact s12-evidence archivé |
| `fix/nonce-persistence-hard-veto-2026-10-09` | 90470e3 | Échecs sur main expliqués par les attestations signées (S7) ; non relue individuellement |
| `fix/resolve-semantics-lei-unlock` | fb01d8a | Comportement présent sur main : test de quarantaine existant et vert en CI |
| `fix/s11-commit-realm-jcs` | 484510a | Non vérifiée individuellement : 11 échecs sur main, à classer |
| `fix/s11-rebased-after-12` | 01cb0d5 | Non vérifiée individuellement : 2 échecs sur main |
| `fix/s11-signed-realm-jcs-vectors` | 01cb0d5 | Non vérifiée individuellement : 2 échecs sur main |
| `exp/s1-real-evidence` | 3da7151 | Expérience fermée (groupe C) |
| `exp/s1-real-policyengine` | 6df762b | Expérience fermée (groupe C) |
| `experiment/s12-nd1-realm-divergence` | 311bc3a | Expérience fermée (groupe C) |
| `experiment/runtime-stress-rig` | 5d88605 | Rejetée : réimplémentation parallèle du membrane (voir issue) |

## Exceptions

- `diagnostic/e2-caller-nonce-and-exceptions-2026-10-09` — SHA pinné `a06aa7c`. 28 commits, non appliqués sur main : l'explorateur de main n'a pas la fonction `nonce_for`. À tracker : décider si les comptes v2 doivent être régénérés après application.
