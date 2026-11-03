Hey Ben and Moab Team!

Thanks for giving me the opportunity to work through this case study. Was fun thinking about a messy old system and how far you can get the data into the new one without making anything up.

We loaded Keystone one layer at a time and checked each layer before moving on. If something required was missing, or we couldn't tell what was right, we left that record out and put it on Carmen's sheet.

What's in here:

- `data/raw/` is LeaseLedger, saved the way it came down.
- `data/ready/` is what we were willing to send.
- `data/review/` is Carmen's spreadsheets and the note that goes with them.
- `data/answers.json` is the three questions.
- `writeup.md` is the short version of the calls we made.
- `docs/rules.md` is the rules we wrote down before loading anything.
- `scripts/` is the download, the cleanup, the load, and the answers. `04_load.py` takes one layer at a time, like `python3 scripts/04_load.py accounts`.

From this folder, with Python 3:

```bash
python3 scripts/01_download.py
python3 scripts/02_look.py
python3 scripts/03_prepare.py
python3 scripts/04_load.py portfolios
python3 scripts/06_answers.py
```

The load script also does `unit_types`, `terms`, `properties`, `vendors`, `accounts`, `contacts`, `primary_contacts`, `units`, and `leases`, in that order. `python3 scripts/04_load.py reset` wipes Keystone and leaves the old files alone.
