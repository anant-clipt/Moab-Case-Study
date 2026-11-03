# Mesa Property Group move

Mesa is moving from LeaseLedger (the old system) to Keystone (the new one). This repo is the work for that move.

Carmen Ortiz runs operations at Mesa. The notes and spreadsheets in here are written for her, in plain language.

## What is in here

- `docs/rules.md` says what we load, what we leave out, and why.
- `docs/what-we-found.md` is the messy stuff we saw in the old data.
- `docs/note-to-carmen.md` is the letter that goes with the spreadsheets.
- `data/raw/` is a copy of the old data, unchanged.
- `data/ready/` is what we send to Keystone.
- `data/review/` is the spreadsheets Carmen uses to fix what we could not.
- `scripts/` is the code that downloads, cleans, loads, and checks.

## How to run it

From this folder, with Python 3:

```bash
python3 scripts/01_download.py
python3 scripts/02_look.py
python3 scripts/03_prepare.py
python3 scripts/04_load.py
python3 scripts/05_check.py
python3 scripts/06_answers.py
```

Each script reads the files from the step before it. We can wipe Keystone and load again. That does not touch the old data.

We do not send the final package until the note to Carmen has been read.
