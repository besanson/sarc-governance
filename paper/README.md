# SARC Paper

This directory contains the LaTeX source for the SARC paper.

## Files

| File | Description |
|---|---|
| `SARC6_paper.tex` | LaTeX source (revision 6) |

## Compiling

```bash
pdflatex SARC6_paper.tex
bibtex SARC6_paper
pdflatex SARC6_paper.tex
pdflatex SARC6_paper.tex
```

Or with `latexmk`:

```bash
latexmk -pdf SARC6_paper.tex
```

## Citation / DOI

A compiled PDF and DOI will be added here once the paper is published.
If you have access to the published version, place `SARC6_paper.pdf` in
this directory.

## Abstract

SARC (Specification-Adherent Runtime Constraints) is a runtime governance
architecture for tool-using agentic AI systems.  It treats constraints as
first-class governance objects with a class (`hard` / `soft` / `escalation`),
an enforcement point (`PAG` / `ATM` / `PAA`), and a required response.
The architecture provides a formal specification-trace correspondence check
and benchmarks five governance regimes in a synthetic procurement domain,
showing that SARC achieves zero hard-constraint bypasses and a 90%
reduction in soft-overage exposure.
