# OED Stardict Prettifier

A Python script designed to process a TSV (Tab-Separated Values) export of the Oxford English Dictionary (OED), clean up its HTML formatting, split homographs into separate entries, and generate a well-structured Stardict dictionary.

## Description

The original OED 2ed originally published in 1989, has been converted to Stardict however it contains messy HTML with inline styles, inconsistent structures, and multiple homographs merged into a single entry. This script addresses these issues by:

* **Splitting Homographs**: It correctly identifies and separates distinct homographs (words with the same spelling but different meanings) into individual dictionary entries.
* **Cleaning & Structuring HTML**: It uses a series of regular expressions to replace inline CSS styles with semantic class names, structure the entry content (e.g., etymology, forms, quotations), and clean up various formatting quirks.
* **Handling Abbreviations**: It correctly processes entries that are abbreviations and creates alternative search keys without the full stop for easier look-up in KOReader.
* **Generating Stardict Files**: It uses the `pyglossary` library to write the processed data into a complete set of Stardict dictionary files (`.ifo`, `.dict.dz`, `.idx`, `.syn`).

The ultimate goal is to produce a "prettified" and more usable version of the OED for dictionary applications like GoldenDict or KOReader, which use the Stardict format.

## Dependencies

To run this script, you will need:

* **Python 3.9+**
* **PyGlossary**: A Python library for converting dictionary formats.
* **dictzip**: A command-line tool for compressing Stardict dictionary files. It is part of the `dictd` package on most Linux distributions.

## Installation

**Clone or download the script.**

**Install PyGlossary:**
```bash
pip install pyglossary
```

**Install dictzip:**
* **On Debian/Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install dictzip
```
* **On macOS (using Homebrew):**
```bash
brew install dictzip
```

## Usage

First you will need to convert your existing copy of the OED to a `.tsv` file, you can do so by running

```
pyglossary ode_file_name.ifo ode_new_name.tsv
```

The script is run from the command line and accepts two arguments: the path to the input TSV file and the base name for the output Stardict files.

### Syntax

```bash
python oed_prettifier.py <input_tsv_path> <output_ifo_name>
```

### Arguments

* `input_tsv_path`: The full path to the source dictionary file in TSV format.
* `output_ifo_name`: The desired base name for the output files. The script will generate files like `OED_2ed.ifo`, `OED_2ed.idx`, etc., from this name. You do not need to provide an extension, i.e., `.ifo`.

### Example

```bash
python3.13 oed_prettifier.py /dictionaries/OED_raw.tsv OED_2ed_prettified
```


## How It Works

The script's logic is divided into two main parts: the main processing loop (`run_processing`) and the HTML cleanup function (`process_html`).

### `run_processing`

* File Reading: Opens and reads the input TSV file line by line.
* Entry Parsing: Each non-metadata line is split into a `word` and its `definition`.
* Homograph Splitting: The core logic for separating entries. It uses a pattern to identify the start of a new homograph and split the definition content accordingly.
* HTML Processing: Each split part (or the whole definition if no homographs are found) is passed to the `process_html` function for cleaning.
* Headword Management: The script ensures that each final entry has a clearly defined headword.
* Abbreviation Handling: For words ending in a full stop (e.g., "adj."), it cleans up duplicated definition text and creates a synonym entry without the full stop (e.g., "adj") to improve searchability.
* Stardict Writing: After processing all lines, it uses `pyglossary` to write the final, cleaned entries to the Stardict files.
* Decompression: It automatically decompresses the `.syn.dz` file to a plain `.syn` file for compatibility with KOReader.

### `process_html`

This function is a pipeline of regular expression substitutions that transform the raw HTML into a cleaner, more semantic format. Key transformations include:

* Removing `<img>` tags and escaped newline/tab characters.
* Wrapping phonetic transcriptions, quotations, and cross-references (`kref`) in spans with corresponding classes (`phonetic`, `quotations`, `kref`).
* Identifying and wrapping distinct sections like **etymology**, **forms**, and **usage notes** in `<div>` tags with appropriate classes.
* Replacing inline color styles for sense numbers (e.g., `[1.]`, `[a.]`, `[I.]`) with semantic classes like `.senses`, `.subsenses`, and `.major-division`.
* Standardising the formatting of dates, authors, and titles within quotation blocks.

Cleaning up other miscellaneous formatting issues.


## Screnshots

#### before
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_173921" src="https://github.com/user-attachments/assets/179e676c-2958-4fd6-a10d-b06482d23312" />
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_174125" src="https://github.com/user-attachments/assets/a0a8eae5-3da7-4d0b-abf3-49ef2088cced" />

#### after
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_173932" src="https://github.com/user-attachments/assets/9318559d-f48f-4bd5-b8a5-aa6d8c9f1a9c" />
<img width=40% alt="Reader_THE MASTER AND MARGARITA (Penguin Classics - Mikhail Bulgakov epub_p147_2025-08-17_174115" src="https://github.com/user-attachments/assets/7cae28c0-4a17-449a-ab15-93acc4c89aef" />
