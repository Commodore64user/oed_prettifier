# OED Stardict Prettifier

A Python script designed to process a TSV (Tab-Separated Values) export of the Oxford English Dictionary (OED), clean up its HTML formatting, split homographs into separate entries, and generate a well-structured Stardict dictionary. Note, the OED is **not** provided here, you must supply your own copy to use this tool.

## Description

The Oxford English Dictionary 2ed (originally published in 1989), which has been converted to Stardict, contains messy HTML with inline styles, inconsistent structures, and multiple homographs merged into single entries. This script addresses these issues by:

* **Splitting Homographs**: It correctly identifies and separates distinct homographs (words with the same spelling but different meanings and origins) into individual dictionary entries.
* **Cleaning & Structuring HTML**: It uses a series of regular expressions to replace inline CSS styles with semantic class names, structure the entry content (e.g., etymology, forms, quotations), and clean up various formatting quirks.
* **Handling Abbreviations**: It processes entries that are abbreviations and creates alternative search keys (stardict synonyms) without the full stop for easier look-up in KOReader.
* **Generating Stardict Files**: It uses the `pyglossary` library to write the processed data into a complete set of Stardict dictionary files (`.ifo`, `.dict.dz`, `.idx`, `.syn`, `.css`).

## Editorial notes

* **Adherence to source**: I have aimed to remain as close as possible to the original presentation and style of the source. Any entry can be verified through the OED website (subscription or library card required). For the second edition, click the 'entry history' link (top left of any headword) and select ‘view in OED Second Edition’. I have, however, introduced a few slight alterations to improve readability on e-ink screens. The most notable is the encapsulation of the etymology, making it easier to identify where to begin reading each entry.
* **Editorial limitations**: Despite extensive efforts, it has been difficult to achieve a perfect 1:1 correspondence with the original OED entries. Through [previous] conversion processes, minor details and editorial nuances have been lost that could realistically only be recovered through manual revision of each individual entry (and that would take _years_). Note: Do not solely rely on this Stardict version if you must make professional citations, do visit the OED website to always make sure all information is correct and up to date.

The ultimate goal is to produce a "prettified" and more usable version of the OED for applications like GoldenDict or KOReader, which use the Stardict format.

## Dependencies

To run this script, you will need:

* Python 3.10+
* PyGlossary: A Python library for converting dictionary formats.
* Beautifulsoup4: A Python library for parsing and pulling data out of HTML and XML files.
* dictzip: A command-line tool for compressing files. It is part of the `dictd` package on most Linux distributions.

## Installation (on macOS)

Clone the repo or download the zipped script files.

**Install PyGlossary:**
```bash
python3 pip install pyglossary beautifulsoup4 lxml
```

* **On macOS (using Homebrew):**
```bash
brew install dictzip
```

## Usage

First you will need to convert your existing copy of the OED to a `.tsv` file, you can do so by running

```
pyglossary oed_file_name.ifo oed_new_name.tsv
```

The script is run from the command line and accepts four arguments: the path to the input TSV file, the base name for the output Stardict files, an optional flag for adding synonyms and the number of workers to be used (more info further down).

### Syntax

```bash
python oed_prettifier.py <input_tsv_path> <output_ifo_name> [--add-syns] [--workers N]
```

### Arguments

* `input_tsv_path`: The full path to the source dictionary file in TSV format.
* `output_ifo_name`: The desired base name for the output files. The script will generate files like `OED_2ed.ifo`, `OED_2ed.idx`, etc., from this name. You do not need to provide an extension, i.e., `.ifo`.
* `--add-syns`: (optional) This flag will inspect each definition and add any bold tags it encounters as synonyms. Note: this will add roughly half million synonyms to the `.syn` file, so use at your own discretion.
* `--workers N`: (optional) By default, the script uses (N = logical cores - 1) as the number of workers. For example, on a system with 8 logical cores, it will use 7 workers. However, for CPU-intensive operations (HTML parsing and regex processing), using (N = physical cores + 1) workers may be more efficient.

### Example

on a quad-core processor with hyper-threading:

* * logical cores: 8
* * physical cores: 4
* * default workers: 7 (logical cores - 1)
* * potentially optimal: 5 workers (physical cores + 1)

```bash
python3.13 oed_prettifier.py /dictionaries/OED_raw.tsv OED_2ed_prettified --add-syns --workers 5
```

Ensure all script files are placed together in the same directory, including the `style.css` file. This ensures all the necessary files for your new Stardict version are generated correctly. If `style.css` is missing from the directory, the script will not create a `.css` file; in that case, rename the existing `style.css` to match your chosen filename (`OED_2ed_prettified` in the previous example). You’re now ready to enjoy your new Stardict version of the OED.

## How It Works

The script is built around an object-oriented design with four core components, each handling a distinct part of the conversion process.

### `DictionaryConverter` (The Orchestrator)

This is the main engine of the script. It manages the entire workflow from reading the input file to writing the final dictionary.

* **File Handling**: It reads the source TSV file line by line and delegates tasks to its team (workers), waits for them to report back, and then assembles the final product. It doesn't do any of the granular, intensive labour itself.
* **Glossary Building**: It manages the `pyglossary` object, adding each processed entry. Finally, it writes the completed Stardict files and decompresses the `.syn.dz` file for KOReader compatibility.
* **Metrics**: It handles the final client-facing summary report (the metrics).

### `processing_worker` (The Workers)

This module contains the deidcated workers who do all the heavy lifting. Each worker process takes a single task, delegates the intensive labour of HTML parsing and synonym extraction, and reports its finished component back to the manager.

* **Entry Management**: It parses each entry, handles the quirks of abbreviations (like `adj.`), and determines if an entry contains multiple homographs.
* **Delegation**: It delegates cleaning HTML or extracting synonyms to the corresponding specialist. It creates an `EntryProcessor` instance for cleaning and calls the `SynonymExtractor` to find synonyms.

### `EntryProcessor` (The HTML Cleaner Specialist)

This class is a specialist worker responsible for all low-level HTML manipulation. It takes the raw, messy HTML of a single entry and transforms it into a clean(er), semantic structure.

Its key operations are a pipeline of regular expression substitutions that:
* Remove unwanted tags and formatting characters, etc.
* Wrap distinct sections like **etymology**, **forms**, and **usage notes** in `<div>` tags with appropriate classes.
* Convert inline style attributes (e.g., `style="color:..."`) for sense numbers (`[1.]`, `[a.]`, etc.) into semantic CSS classes like `.senses` and `.subsenses`.
* Identify and wrap phonetic transcriptions, quotations, and cross-references in `<span>` tags.
* Standardise the format of dates, authors, and titles within quotations.

### `SynonymExtractor` (The Keyword Miner Specialist)

This is a specialised utility class for finding and cleaning potential synonyms, which are used as alternative search keys in the dictionary.

* **Extraction**: It parses the cleaned HTML of an entry to find all text contained within bold (`<b>`) tags, which often represent alternative forms, compounds, or related phrases.
* **Cleaning**: Each potential synonym is passed through a cleaning process to remove punctuation, symbols, and other noise.
* **Filtering**: It filters out common English words (like 'and', 'the', 'of') and fragments to produce a useful list of keywords.

**Note**: This is an optional step that significantly increases the script's running time (depending on your system, this can be approximately 2x-4x slower) due to the overhead of parsing every entry's HTML.


## Screnshots

#### before (e-ink)
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_173921" src="https://github.com/user-attachments/assets/179e676c-2958-4fd6-a10d-b06482d23312" />
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_174125" src="https://github.com/user-attachments/assets/a0a8eae5-3da7-4d0b-abf3-49ef2088cced" />

#### after (e-ink)
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_173932" src="https://github.com/user-attachments/assets/9318559d-f48f-4bd5-b8a5-aa6d8c9f1a9c" />
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_174115" src="https://github.com/user-attachments/assets/7cae28c0-4a17-449a-ab15-93acc4c89aef" />

#### after (colour - homographs)
<img width=40% alt="Reader_herman-melville_moby-dick epub_p41_2025-08-18_005138" src="https://github.com/user-attachments/assets/54080a17-4543-4e59-94f8-a004311c463a" />
<img width=40% alt="Reader_herman-melville_moby-dick epub_p41_2025-08-18_005051" src="https://github.com/user-attachments/assets/9bd50a9e-f59f-4eec-a21d-7f2dc49a9046" />

