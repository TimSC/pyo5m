"""Converts between formats, streaming so the file never has to fit in memory:

	python3 examples/convert.py tests/data/o5mtest.o5m out.osm.gz
"""
import sys
import pyo5m

if __name__ == "__main__":
	source_path, target_path = sys.argv[1:3]
	with pyo5m.open_file(source_path) as source, pyo5m.open_file(target_path, "wb") as target:
		encoder = pyo5m.encoder(target, pyo5m.format_of(target_path)[0])
		pyo5m.decoder(source, encoder, pyo5m.format_of(source_path)[0]).run()
