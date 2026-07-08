# Fixture attribution

- `rw_gold.csv` contains a small extract of real rows from the **Retraction
  Watch Database**, made openly available by **Crossref**
  (https://gitlab.com/crossref/retraction-watch-data). Rows are included
  solely as a reproducible evaluation set, with gratitude to Retraction Watch /
  The Center for Scientific Integrity. Verify current redistribution terms
  before expanding this extract.
- `openalex/*.json` are recorded (or historical-shaped) OpenAlex work records.
  OpenAlex metadata is CC0. `10_2807_..._2000045.json` deliberately carries the
  historical `is_retracted: true` shape for the Corman-Drosten paper to test
  the false-positive guard — live OpenAlex no longer reports this. Do not
  overwrite it.
- `crossref/*.json` are recorded Crossref notice lists (empty where a work has
  no editorial notice). Crossref metadata is open.
