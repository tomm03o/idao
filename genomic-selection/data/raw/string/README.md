# STRING Protein-Protein Interaction Networks

This directory contains **real protein interaction data** downloaded from STRING Database v12.0.

## 🚫 Not Committed to Git

These files are **excluded from git** due to their large size (461 MB total).

## 📥 How to Download

Run the automatic downloader:

```bash
cd genomic-selection
python data/downloaders/download_string.py
```

This will download:
- Human (Homo sapiens, taxid 9606)
- Cattle (Bos taurus, taxid 9913)
- Dog (Canis lupus familiaris, taxid 9615)

## 📊 Expected Files

After running the downloader, you should have:

```
data/raw/string/
├── 9606.protein.links.v12.0.txt.gz       (80 MB)
├── 9606.protein.info.v12.0.txt.gz        (2 MB)
├── 9913.protein.links.v12.0.txt.gz       (72 MB)
├── 9913.protein.info.v12.0.txt.gz        (1 MB)
├── 9615.protein.links.v12.0.txt.gz       (59 MB)
├── 9615.protein.info.v12.0.txt.gz        (560 KB)
├── human_interactions_filtered.tsv       (82 MB)
├── cattle_interactions_filtered.tsv      (91 MB)
└── dog_interactions_filtered.tsv         (77 MB)
```

**Total size: ~461 MB**

## ℹ️ Data Source

- **Database**: STRING v12.0
- **Website**: https://string-db.org/
- **License**: Free for academic use
- **Citation**: Szklarczyk et al. (2023) Nucleic Acids Research

## 🔍 Contents

### Protein Links (interactions)
- Confidence scores 0-1000
- Filtered to score ≥ 400 (medium-high confidence)
- Experimental + computational predictions

### Protein Info
- Protein IDs
- Gene names
- Annotations

## 🎯 Usage in Platform

These networks are used for:
1. **PathwayGNN** - Graph neural network training
2. **Protein-protein interaction analysis**
3. **Cross-species network comparison**
4. **Pathway completeness scoring**
