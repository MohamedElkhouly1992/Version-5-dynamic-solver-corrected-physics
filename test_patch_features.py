from io import BytesIO
import io
import zipfile
import pandas as pd

from robust_io import read_csv_robust
from publication_export import make_publication_bundle


def test_robust_csv_encodings():
    cases=[
        ('utf-8', ',', 'a,b\n1,2\n'),
        ('cp1252', ';', 'name;value\nCaf\xe9;3\n'),
        ('utf-16', '\t', 'a\tb\n1\t2\n'),
    ]
    for enc, sep, text in cases:
        df=read_csv_robust(BytesIO(text.encode(enc)))
        assert df.shape == (1,2)


def test_publication_bundle_contents():
    b=make_publication_bundle({'table':pd.DataFrame({'x':[1.23456789]})},metadata={'seed':42})
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        names=set(z.namelist())
    assert 'publication_results.xlsx' in names
    assert 'tables_raw/table.csv' in names
    assert 'tables_publication/table.csv' in names
    assert 'metadata/run_manifest.json' in names

if __name__ == '__main__':
    test_robust_csv_encodings(); test_publication_bundle_contents(); print('PATCH TESTS PASSED')
