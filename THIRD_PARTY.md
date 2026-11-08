# Data and dependency credits

The historical input is [OpenFootball JSON](https://github.com/openfootball/football.json/tree/e6744429ee395bc86f247348c6184bb08d4eb361), revision `e6744429ee395bc86f247348c6184bb08d4eb361`. Dates and scores were compared with [OpenFootball England](https://github.com/openfootball/england/tree/9ee7a0c351805c99cc334478a9bf04b7d0432fec), revision `9ee7a0c351805c99cc334478a9bf04b7d0432fec`. Both repositories describe their data as public domain and supply CC0 1.0 Universal terms.

An unchanged copy of those data terms is in [licenses/openfootball-CC0-1.0.txt](licenses/openfootball-CC0-1.0.txt). The license applies to the contributors' rights in the data. It does not clear third-party rights or grant rights in club crests, photographs, league branding, or unrelated official content. Dataset files are supplied separately from the source code.

The Python dependencies and exact versions are listed in `requirements.lock`. Their distributions retain their own licensing notices. This project uses pandas, NumPy, SciPy, scikit-learn, Matplotlib, joblib and the IANA timezone data distributed through tzdata.
